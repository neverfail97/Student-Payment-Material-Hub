from flask import Flask, render_template, request, jsonify, send_file
import os
import requests
from datetime import date, datetime
from io import BytesIO
from functools import wraps
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm
from xml.sax.saxutils import escape

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

FONT_DIR = os.path.join(os.path.dirname(__file__), "static", "fonts")
FONT_REGULAR = os.path.join(FONT_DIR, "DejaVuSans.ttf")
FONT_BOLD = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
if os.path.exists(FONT_REGULAR):
    pdfmetrics.registerFont(TTFont("AppSans", FONT_REGULAR))
if os.path.exists(FONT_BOLD):
    pdfmetrics.registerFont(TTFont("AppSans-Bold", FONT_BOLD))
PDF_FONT = "AppSans" if "AppSans" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
PDF_BOLD = "AppSans-Bold" if "AppSans-Bold" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"


def configured():
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY)


def auth_user():
    """Validate the Supabase access token and return the authenticated user."""
    if not configured():
        return None, "Supabase environment variables are not configured."
    token = request.headers.get("Authorization", "")
    if not token.startswith("Bearer "):
        return None, "Please sign in."
    try:
        r = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_ANON_KEY, "Authorization": token},
            timeout=10,
        )
        if r.ok:
            return r.json(), None
    except requests.RequestException:
        pass
    return None, "Your session has expired. Please sign in again."


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user, error = auth_user()
        if not user:
            return jsonify({"error": error}), 401
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapped


def sb_request(method, table, params=None, body=None, headers=None):
    if not configured():
        raise RuntimeError("Supabase is not configured. Add the required environment variables.")
    h = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if headers:
        h.update(headers)
    r = requests.request(
        method, f"{SUPABASE_URL}/rest/v1/{table}",
        params=params or {}, json=body, headers=h, timeout=15
    )
    if not r.ok:
        try:
            detail = r.json().get("message") or r.json().get("hint") or r.text
        except Exception:
            detail = r.text
        raise RuntimeError(detail or "Database request failed.")
    if not r.content:
        return []
    try:
        return r.json()
    except Exception:
        return []


def uid():
    return request.current_user["id"]


def get_settings():
    rows = sb_request("GET", "settings", {
        "user_id": f"eq.{uid()}",
        "select": "key,value",
        "order": "key.asc",
    })
    values = {r["key"]: r["value"] for r in rows}
    return {
        "common_required_amount": float(values.get("common_required_amount", "100")),
        "required_materials": [x.strip() for x in values.get(
            "required_materials", "Notes, Lab Manual, Record Note"
        ).split(",") if x.strip()],
        "today": date.today().isoformat(),
    }


def save_setting(key, value):
    sb_request(
        "POST", "settings",
        body={"user_id": uid(), "key": key, "value": str(value)},
        headers={"Prefer": "resolution=merge-duplicates,return=representation"},
    )


def fetch_students():
    return sb_request("GET", "students", {
        "user_id": f"eq.{uid()}",
        "select": "student_id,roll_no,student_name,required_amount",
        "order": "roll_no.asc",
    })


def fetch_payments(student_ids=None):
    params = {
        "user_id": f"eq.{uid()}",
        "select": "payment_id,student_id,amount_paid,payment_mode,transaction_details,payment_date",
        "order": "payment_id.asc",
    }
    if student_ids is not None:
        if not student_ids:
            return []
        params["student_id"] = "in.(" + ",".join(str(int(x)) for x in student_ids) + ")"
    return sb_request("GET", "payments", params)


def fetch_materials(student_ids=None):
    params = {
        "user_id": f"eq.{uid()}",
        "select": "material_id,student_id,material_name,received_status,received_date",
        "order": "material_id.asc",
    }
    if student_ids is not None:
        if not student_ids:
            return []
        params["student_id"] = "in.(" + ",".join(str(int(x)) for x in student_ids) + ")"
    return sb_request("GET", "materials", params)


def all_records():
    students = fetch_students()
    ids = [s["student_id"] for s in students]
    payments = fetch_payments(ids)
    materials = fetch_materials(ids)

    by_student_payments = {i: [] for i in ids}
    by_student_materials = {i: [] for i in ids}
    for p in payments:
        by_student_payments.setdefault(p["student_id"], []).append(p)
    for m in materials:
        by_student_materials.setdefault(m["student_id"], []).append(m)

    result = []
    for row in students:
        sid = row["student_id"]
        ps = by_student_payments.get(sid, [])
        ms = by_student_materials.get(sid, [])
        paid = sum(float(p["amount_paid"] or 0) for p in ps)
        required = float(row["required_amount"] or 0)
        balance = max(required - paid, 0)
        status = (
            "Unpaid" if paid == 0 else
            "Pending" if paid < required else
            "Paid" if paid == required else
            "Amount Exceeding"
        )
        received = sum(m["received_status"] == "Received" for m in ms)
        modes = []
        for p in ps:
            if p["payment_mode"] not in modes:
                modes.append(p["payment_mode"])
        result.append({
            "student_id": sid,
            "roll_no": row["roll_no"],
            "student_name": row["student_name"],
            "required_amount": required,
            "amount_paid": paid,
            "remaining_amount": balance,
            "excess_amount": max(paid - required, 0),
            "payment_mode": ", ".join(modes) if modes else "None",
            "payment_count": len(ps),
            "payment_status": status,
            "materials": ms,
            "materials_received": received,
            "materials_total": len(ms),
        })
    return result


@app.route("/")
def index():
    return render_template("index.html", supabase_config={
        "url": SUPABASE_URL,
        "anon_key": SUPABASE_ANON_KEY,
    })


@app.route("/api/health")
def health():
    return jsonify({"configured": configured()})


@app.route("/api/settings", methods=["GET", "POST"])
@login_required
def settings_api():
    try:
        if request.method == "POST":
            data = request.get_json() or {}
            try:
                amount = float(data.get("common_required_amount", 0))
                if amount <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({"error": "Required amount must be a positive number."}), 400
            materials = [x.strip() for x in str(data.get("required_materials", "")).split(",") if x.strip()]
            if not materials:
                return jsonify({"error": "Enter at least one required material."}), 400

            save_setting("common_required_amount", amount)
            save_setting("required_materials", ", ".join(materials))
            sb_request("PATCH", "students", {
                "user_id": f"eq.{uid()}",
            }, {"required_amount": amount})
        return jsonify(get_settings())
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/students", methods=["GET", "POST"])
@login_required
def students_api():
    try:
        if request.method == "GET":
            return jsonify(all_records())

        data = request.get_json() or {}
        roll = str(data.get("roll_no", "")).strip()
        name = str(data.get("student_name", "")).strip()
        if not roll or not name:
            return jsonify({"error": "Roll number and student name are required."}), 400

        required = get_settings()["common_required_amount"]
        try:
            rows = sb_request("POST", "students", body={
                "user_id": uid(), "roll_no": roll, "student_name": name, "required_amount": required
            }, headers={"Prefer": "return=representation"})
        except RuntimeError as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                return jsonify({"error": "That roll number/ID already exists."}), 409
            raise
        return jsonify(all_records()[next(
            i for i, s in enumerate(all_records()) if s["student_id"] == rows[0]["student_id"]
        )]), 201
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/students/<int:student_id>", methods=["PUT", "DELETE"])
@login_required
def student_detail(student_id):
    try:
        exists = sb_request("GET", "students", {
            "user_id": f"eq.{uid()}",
            "student_id": f"eq.{student_id}",
            "select": "student_id",
        })
        if not exists:
            return jsonify({"error": "Student not found."}), 404

        if request.method == "DELETE":
            sb_request("DELETE", "students", {
                "user_id": f"eq.{uid()}",
                "student_id": f"eq.{student_id}",
            })
            return jsonify({"ok": True})

        data = request.get_json() or {}
        roll = str(data.get("roll_no", "")).strip()
        name = str(data.get("student_name", "")).strip()
        if not roll or not name:
            return jsonify({"error": "Name and ID are required."}), 400
        try:
            sb_request("PATCH", "students", {
                "user_id": f"eq.{uid()}",
                "student_id": f"eq.{student_id}",
            }, {"roll_no": roll, "student_name": name})
        except RuntimeError as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                return jsonify({"error": "That student ID already exists."}), 409
            raise
        return jsonify(next(s for s in all_records() if s["student_id"] == student_id))
    except (RuntimeError, StopIteration) as e:
        return jsonify({"error": str(e) or "Student not found."}), 500


@app.route("/api/students/<int:student_id>/payments", methods=["POST"])
@login_required
def payment_api(student_id):
    try:
        data = request.get_json() or {}
        try:
            amount = float(data.get("amount_paid", 0))
        except (TypeError, ValueError):
            amount = 0
        mode = data.get("payment_mode")
        details = str(data.get("transaction_details", "")).strip()
        pdate = data.get("payment_date") or date.today().isoformat()
        if amount <= 0 or mode not in ("UPI", "Cash"):
            return jsonify({"error": "Enter a valid amount and payment mode."}), 400

        student = sb_request("GET", "students", {
            "user_id": f"eq.{uid()}", "student_id": f"eq.{student_id}", "select": "student_id"
        })
        if not student:
            return jsonify({"error": "Student not found."}), 404
        sb_request("POST", "payments", body={
            "user_id": uid(), "student_id": student_id, "amount_paid": amount,
            "payment_mode": mode, "transaction_details": details, "payment_date": pdate
        })
        return jsonify(next(s for s in all_records() if s["student_id"] == student_id))
    except (RuntimeError, StopIteration) as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/payments/<int:payment_id>", methods=["PUT", "DELETE"])
@login_required
def payment_detail(payment_id):
    try:
        p = sb_request("GET", "payments", {
            "user_id": f"eq.{uid()}", "payment_id": f"eq.{payment_id}",
            "select": "payment_id,student_id",
        })
        if not p:
            return jsonify({"error": "Payment not found."}), 404
        if request.method == "DELETE":
            sb_request("DELETE", "payments", {
                "user_id": f"eq.{uid()}", "payment_id": f"eq.{payment_id}"
            })
            return jsonify({"ok": True})

        data = request.get_json() or {}
        try:
            amount = float(data.get("amount_paid", 0))
        except (TypeError, ValueError):
            amount = 0
        mode = data.get("payment_mode")
        if amount <= 0 or mode not in ("UPI", "Cash"):
            return jsonify({"error": "Invalid payment."}), 400
        sb_request("PATCH", "payments", {
            "user_id": f"eq.{uid()}", "payment_id": f"eq.{payment_id}"
        }, {
            "amount_paid": amount, "payment_mode": mode,
            "transaction_details": str(data.get("transaction_details", "")).strip(),
            "payment_date": data.get("payment_date") or date.today().isoformat(),
        })
        return jsonify(next(s for s in all_records() if s["student_id"] == p[0]["student_id"]))
    except (RuntimeError, StopIteration) as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/students/<int:student_id>/materials", methods=["POST"])
@login_required
def material_batch(student_id):
    try:
        data = request.get_json() or {}
        items = data.get("materials", [])
        mdate = data.get("received_date") or date.today().isoformat()
        student = sb_request("GET", "students", {
            "user_id": f"eq.{uid()}", "student_id": f"eq.{student_id}", "select": "student_id"
        })
        if not student:
            return jsonify({"error": "Student not found."}), 404

        for item in items:
            name = str(item.get("name", "")).strip()
            status = item.get("status")
            if not name or status not in ("Received", "Not Received"):
                continue
            existing = sb_request("GET", "materials", {
                "user_id": f"eq.{uid()}", "student_id": f"eq.{student_id}",
                "material_name": f"eq.{name}", "select": "material_id",
            })
            payload = {
                "received_status": status,
                "received_date": mdate if status == "Received" else None,
            }
            if existing:
                sb_request("PATCH", "materials", {
                    "user_id": f"eq.{uid()}",
                    "material_id": f"eq.{existing[0]['material_id']}",
                }, payload)
            else:
                sb_request("POST", "materials", body={
                    "user_id": uid(), "student_id": student_id, "material_name": name, **payload
                })
        return jsonify(next(s for s in all_records() if s["student_id"] == student_id))
    except (RuntimeError, StopIteration) as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/materials/<int:material_id>", methods=["PUT", "DELETE"])
@login_required
def material_detail(material_id):
    try:
        m = sb_request("GET", "materials", {
            "user_id": f"eq.{uid()}", "material_id": f"eq.{material_id}",
            "select": "material_id,student_id",
        })
        if not m:
            return jsonify({"error": "Material not found."}), 404
        if request.method == "DELETE":
            sb_request("DELETE", "materials", {
                "user_id": f"eq.{uid()}", "material_id": f"eq.{material_id}"
            })
            return jsonify({"ok": True})

        data = request.get_json() or {}
        status = data.get("received_status")
        if status not in ("Received", "Not Received"):
            return jsonify({"error": "Invalid material status."}), 400
        sb_request("PATCH", "materials", {
            "user_id": f"eq.{uid()}", "material_id": f"eq.{material_id}"
        }, {
            "received_status": status,
            "received_date": (data.get("received_date") or date.today().isoformat()) if status == "Received" else None,
        })
        return jsonify(next(s for s in all_records() if s["student_id"] == m[0]["student_id"]))
    except (RuntimeError, StopIteration) as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/summary")
@login_required
def summary():
    try:
        recs = all_records()
        total_required = sum(x["required_amount"] for x in recs)
        total_paid = sum(x["amount_paid"] for x in recs)
        payments = fetch_payments()
        cash = sum(float(p["amount_paid"]) for p in payments if p["payment_mode"] == "Cash")
        upi = sum(float(p["amount_paid"]) for p in payments if p["payment_mode"] == "UPI")
        cash_students = len({p["student_id"] for p in payments if p["payment_mode"] == "Cash"})
        upi_students = len({p["student_id"] for p in payments if p["payment_mode"] == "UPI"})
        mat_counts = {}
        for x in recs:
            mat_counts[x["materials_received"]] = mat_counts.get(x["materials_received"], 0) + 1
        return jsonify({
            "total_students": len(recs), "total_required": total_required,
            "total_paid": total_paid, "total_pending": max(total_required - total_paid, 0),
            "upi": upi, "cash": cash, "upi_students": upi_students,
            "cash_students": cash_students,
            "materials_received": sum(x["materials_received"] for x in recs),
            "material_counts": mat_counts,
        })
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/report")
@login_required
def report():
    try:
        records = all_records()
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=landscape(A4),
            rightMargin=14 * mm, leftMargin=14 * mm,
            topMargin=18 * mm, bottomMargin=15 * mm,
            title="Weekly Student Payment & Material Distribution Report",
            author="ClassPay",
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], fontName=PDF_BOLD, fontSize=20, leading=24, textColor=colors.HexColor("#172554"), alignment=TA_LEFT, spaceAfter=3)
        subtitle_style = ParagraphStyle("ReportSubtitle", parent=styles["Normal"], fontName=PDF_FONT, fontSize=8.5, leading=12, textColor=colors.HexColor("#64748b"))
        section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontName=PDF_BOLD, fontSize=13, leading=16, textColor=colors.HexColor("#312e81"), spaceBefore=10, spaceAfter=7)
        body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName=PDF_FONT, fontSize=7.8, leading=10, textColor=colors.HexColor("#334155"))
        small_style = ParagraphStyle("Small", parent=body_style, fontSize=7, leading=8.5)
        card_style = ParagraphStyle("Card", parent=styles["Normal"], fontName=PDF_BOLD, fontSize=11, leading=14, textColor=colors.HexColor("#172554"))

        def P(text, style=body_style):
            return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)

        def money(n):
            return f"₹{float(n or 0):,.0f}"

        def footer(canvas, doc_obj):
            canvas.saveState()
            w, _ = landscape(A4)
            canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
            canvas.line(14 * mm, 10 * mm, w - 14 * mm, 10 * mm)
            canvas.setFont(PDF_FONT, 7)
            canvas.setFillColor(colors.HexColor("#64748b"))
            canvas.drawString(14 * mm, 6.5 * mm, "ClassPay • Weekly report")
            canvas.drawRightString(w - 14 * mm, 6.5 * mm, f"Page {doc_obj.page}")
            canvas.restoreState()

        total_required = sum(s["required_amount"] for s in records)
        total_paid = sum(s["amount_paid"] for s in records)
        total_excess = sum(s["excess_amount"] for s in records)
        total_balance = sum(s["remaining_amount"] for s in records)
        paid = sum(s["payment_status"] == "Paid" for s in records)
        pending = sum(s["payment_status"] == "Pending" for s in records)
        unpaid = sum(s["payment_status"] == "Unpaid" for s in records)
        exceeding = sum(s["payment_status"] == "Amount Exceeding" for s in records)

        story = [
            Paragraph("Weekly Student Payment & Material Report", title_style),
            Paragraph(f"Generated {datetime.now().strftime('%d %b %Y, %I:%M %p')}  •  {len(records)} student(s)  •  Required total {money(total_required)}", subtitle_style),
            Spacer(1, 8),
        ]
        cards = [[
            Paragraph(f"<b>{len(records)}</b><br/><font size='7'>STUDENTS</font>", card_style),
            Paragraph(f"<b>{money(total_required)}</b><br/><font size='7'>REQUIRED</font>", card_style),
            Paragraph(f"<b>{money(total_paid)}</b><br/><font size='7'>COLLECTED</font>", card_style),
            Paragraph(f"<b>{money(total_balance)}</b><br/><font size='7'>BALANCE</font>", card_style),
            Paragraph(f"<b>{money(total_excess)}</b><br/><font size='7'>EXCESS</font>", card_style),
        ]]
        card_table = Table(cards, colWidths=[52*mm]*5)
        card_table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(0,0),colors.HexColor("#eef2ff")), ("BACKGROUND",(1,0),(1,0),colors.HexColor("#ecfeff")),
            ("BACKGROUND",(2,0),(2,0),colors.HexColor("#ecfdf5")), ("BACKGROUND",(3,0),(3,0),colors.HexColor("#fff7ed")),
            ("BACKGROUND",(4,0),(4,0),colors.HexColor("#fef2f2")), ("BOX",(0,0),(-1,-1),0.6,colors.HexColor("#cbd5e1")),
            ("INNERGRID",(0,0),(-1,-1),0.6,colors.HexColor("#cbd5e1")), ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LEFTPADDING",(0,0),(-1,-1),9), ("RIGHTPADDING",(0,0),(-1,-1),9), ("TOPPADDING",(0,0),(-1,-1),8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ]))
        story += [card_table, Spacer(1, 6)]

        overview = [
            [P("Payment status", ParagraphStyle("th1", parent=small_style, fontName=PDF_BOLD)), P("Students", ParagraphStyle("th2", parent=small_style, fontName=PDF_BOLD)), P("Cash", ParagraphStyle("th3", parent=small_style, fontName=PDF_BOLD)), P("UPI", ParagraphStyle("th4", parent=small_style, fontName=PDF_BOLD))],
            [P("Paid"), P(paid), P(sum(1 for s in records if "Cash" in s["payment_mode"])), P(sum(1 for s in records if "UPI" in s["payment_mode"]))],
            [P("Pending"), P(pending), P("—"), P("—")], [P("Unpaid"), P(unpaid), P("—"), P("—")], [P("Amount Exceeding"), P(exceeding), P("—"), P("—")],
        ]
        overview_table = Table(overview, colWidths=[55*mm, 35*mm, 35*mm, 35*mm])
        overview_table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#172554")), ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),0.45,colors.HexColor("#cbd5e1")), ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafc")]),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("LEFTPADDING",(0,0),(-1,-1),7), ("RIGHTPADDING",(0,0),(-1,-1),7), ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ]))
        story += [overview_table, Spacer(1, 4)]

        story.append(Paragraph("1. Amount Groups", section_style))
        amount_groups = {}
        for s in records:
            amount_groups.setdefault((s["payment_status"], s["required_amount"]), []).append(s)
        amount_rows = [[P(x, small_style) for x in ["Group", "Required", "Students", "Collected", "Balance", "Excess"]]]
        for (status, required), group in sorted(amount_groups.items(), key=lambda x: (x[0][0], x[0][1])):
            amount_rows.append([P(status), P(money(required)), P(len(group)), P(money(sum(x["amount_paid"] for x in group))), P(money(sum(x["remaining_amount"] for x in group))), P(money(sum(x["excess_amount"] for x in group)))])
        amount_table = Table(amount_rows, colWidths=[48*mm,35*mm,30*mm,38*mm,38*mm,35*mm], repeatRows=1)
        amount_table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#4338ca")), ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#cbd5e1")), ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f5f3ff")]),
            ("ALIGN",(1,1),(-1,-1),"RIGHT"), ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("FONTNAME",(0,0),(-1,0),PDF_BOLD), ("FONTSIZE",(0,0),(-1,-1),7.5),
            ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6), ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ]))
        story.append(amount_table)

        story.append(Paragraph("2. Student-wise Cases", section_style))
        student_rows = [[P(x, small_style) for x in ["ID","Student","Required","Paid","Balance","Excess","Mode","Status","Materials"]]]
        for s in sorted(records, key=lambda x: (str(x["roll_no"]).lower(), str(x["student_name"]).lower())):
            details = ", ".join(f"{m['material_name']}: {m['received_status']}" for m in s["materials"]) or "Not entered"
            student_rows.append([P(s["roll_no"]), P(s["student_name"]), P(money(s["required_amount"])), P(money(s["amount_paid"])), P(money(s["remaining_amount"])), P(money(s["excess_amount"])), P(s["payment_mode"]), P(s["payment_status"]), Paragraph(escape(details), small_style)])
        student_table = Table(student_rows, colWidths=[25*mm,39*mm,27*mm,27*mm,27*mm,27*mm,30*mm,35*mm,70*mm], repeatRows=1, splitByRow=1)
        student_table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0f766e")), ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#cbd5e1")), ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafc")]),
            ("VALIGN",(0,0),(-1,-1),"TOP"), ("FONTSIZE",(0,0),(-1,-1),6.8), ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5), ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        story.append(student_table)

        story.append(Paragraph("3. Material-wise Cases", section_style))
        material_names = sorted({m["material_name"] for s in records for m in s["materials"]})
        material_rows = [[P(x, small_style) for x in ["Material","Received","Pending / Not Received","Students"]]]
        for name in material_names:
            received_names, pending_names = [], []
            for s in records:
                item = next((m for m in s["materials"] if m["material_name"] == name), None)
                if item and item["received_status"] == "Received":
                    received_names.append(f"{s['roll_no']} • {s['student_name']}")
                else:
                    pending_names.append(f"{s['roll_no']} • {s['student_name']}")
            material_rows.append([P(name), P(len(received_names)), P(len(pending_names)), Paragraph(escape(" • ".join(received_names + pending_names) or "No students"), small_style)])
        if not material_names:
            material_rows.append([P("No material records"), P("0"), P("0"), P("No students")])
        material_table = Table(material_rows, colWidths=[48*mm,28*mm,38*mm,173*mm], repeatRows=1)
        material_table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#7c3aed")), ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#cbd5e1")), ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#faf5ff")]),
            ("VALIGN",(0,0),(-1,-1),"TOP"), ("FONTSIZE",(0,0),(-1,-1),7.2), ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6), ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ]))
        story.append(material_table)

        if not records:
            story = [Paragraph("Weekly Student Payment & Material Report", title_style), P("No students are currently recorded.", body_style)]

        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=f"student_report_{date.today().isoformat()}.pdf", mimetype="application/pdf")
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
