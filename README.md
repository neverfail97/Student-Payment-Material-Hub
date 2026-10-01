# Student Payment & Material Distribution Management System — Online Edition

The existing dashboard design and workflow are kept. This edition adds:

- Email/password account sign-in and account creation.
- Password reset by email.
- Private data per account.
- Supabase PostgreSQL cloud database.
- Access to the same student/payment/material records from any device after signing into the same account.
- The existing weekly PDF report.
- No passwords or Supabase secret keys are stored in the source code.

## Architecture

Browser → Flask website → Supabase Auth + Supabase PostgreSQL

The browser only receives the Supabase **anon/public key**. The Supabase **service-role key** is used only by the Flask server and must never be placed in HTML, JavaScript, GitHub, or a public repository.

## 1. Create the online database

1. Create a project at https://supabase.com/
2. In Supabase, open **SQL Editor**.
3. Open this project's `schema.sql`.
4. Paste/run the complete SQL file.
5. In Supabase **Authentication → Providers**, keep Email enabled.
6. If you want users to verify their email before first login, keep email confirmation enabled. For a simple classroom deployment, you can choose the confirmation behavior appropriate for your project.

## 2. Get the three Supabase values

In Supabase open **Project Settings → API** and copy:

- Project URL → `SUPABASE_URL`
- Publishable/anon key → `SUPABASE_ANON_KEY`
- Service role key → `SUPABASE_SERVICE_ROLE_KEY`

Never expose the service-role key to the browser.

## 3. Run locally

Create a virtual environment and install dependencies:

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

Set environment variables.

### Windows PowerShell

```powershell
$env:SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
$env:SUPABASE_ANON_KEY="YOUR_ANON_KEY"
$env:SUPABASE_SERVICE_ROLE_KEY="YOUR_SERVICE_ROLE_KEY"
python app.py
```

### macOS/Linux

```bash
export SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
export SUPABASE_ANON_KEY="YOUR_ANON_KEY"
export SUPABASE_SERVICE_ROLE_KEY="YOUR_SERVICE_ROLE_KEY"
python app.py
```

Open `http://127.0.0.1:5000`.

## 4. Deploy as a real website

The project includes `render.yaml` for a Render web service.

1. Push this folder to a private GitHub repository.
2. Create a Render Web Service from that repository.
3. Render can use the included `render.yaml`, or you can enter:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
4. Add the three environment variables in Render:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
5. Deploy.
6. Open the Render website URL from your phone/laptop.
7. Create an account with your email and password.
8. Sign into the same account on another device; the same cloud data will appear.

## Important security notes

- Do not commit `.env` files or service-role keys.
- Treat the Supabase service-role key like a server password.
- The application validates the signed-in Supabase user before every data API request.
- Every database query is scoped to that user's UUID.
- The database also has Row Level Security policies as an additional protection.
- Your users should use their own accounts rather than sharing one password.

## Existing workflow

After sign-in, the dashboard works the same way as before:

1. Set the common amount and required materials.
2. Add students.
3. Select a student.
4. Record payment and materials in one entry.
5. Edit a student's name/ID or add another payment later.
6. Search/filter records.
7. Download the weekly PDF.

The new account controls are limited to signing in/out and password recovery; the main dashboard styling and controls remain unchanged.
