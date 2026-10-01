let students=[]; let settings={common_required_amount:100,required_materials:[]}; let selectedEntryId=null;
let supabaseClient=null; let authMode='login';
const authOverlay=()=>document.getElementById('authOverlay');
function showAuth(message=''){authOverlay().classList.add('open');$('authMessage').textContent=message;$('accountMenu').classList.remove('open');}
function hideAuth(){authOverlay().classList.remove('open');$('authMessage').textContent='';}
function setAuthMode(mode){
  authMode=mode;
  const signup=mode==='signup';
  $('authTitle').textContent=signup?'Create your account':'Sign in to your dashboard';
  $('authSubtitle').textContent=signup?'Your records will be stored in your private online account.':'Your student records are saved securely to your online account.';
  $('authSubmit').textContent=signup?'Create account':'Sign in';
  $('authSwitch').textContent=signup?'Already have an account? Sign in':'Create a new account';
  $('forgotBtn').style.display=signup?'none':'inline-block';
  $('authPassword').autocomplete=signup?'new-password':'current-password';
}
async function initAuth(){
  const cfg=window.SUPABASE_CONFIG||{};
  if(!cfg.url||!cfg.anon_key){showAuth('Online database is not configured yet. Add SUPABASE_URL and SUPABASE_ANON_KEY on the server.');$('authSubmit').disabled=true;return;}
  if(!window.supabase){showAuth('Authentication library could not be loaded. Check your internet connection.');return;}
  supabaseClient=window.supabase.createClient(cfg.url,cfg.anon_key);
  const {data:{session}}=await supabaseClient.auth.getSession();
  if(session) await signedIn(session);
  else showAuth();
  supabaseClient.auth.onAuthStateChange(async(_event,session)=>{
    if(session) await signedIn(session); else {students=[];if($('studentTable'))$('studentTable').innerHTML='<tr><td colspan="9" class="empty">Sign in to view your records.</td></tr>';showAuth();}
  });
}
async function signedIn(session){
  hideAuth();
  $('accountBtn').textContent=session.user.email||'Account';
  $('accountEmail').textContent=session.user.email||'';
  try{await load();}catch(e){toast(e.message,false);}
}
const $=id=>document.getElementById(id); const money=n=>'₹'+Number(n||0).toLocaleString('en-IN',{maximumFractionDigits:0});
function today(){return new Date().toISOString().slice(0,10)}
function toast(msg,ok=true){const t=$('toast');t.textContent=msg;t.className=ok?'show ok':'show err';setTimeout(()=>t.className='',2500)}
async function api(url,opts={}){
  const {data:{session}}=await supabaseClient.auth.getSession();
  const headers={'Content-Type':'application/json',...(opts.headers||{})};
  if(session) headers.Authorization=`Bearer ${session.access_token}`;
  const r=await fetch(url,{...opts,headers});
  let d={}; try{d=await r.json()}catch(_){}
  if(r.status===401){await supabaseClient.auth.signOut();throw Error(d.error||'Please sign in again.')}
  if(!r.ok)throw Error(d.error||'Something went wrong');return d
}
async function load(){settings=await api('/api/settings');students=await api('/api/students');render();$('commonAmount').value=settings.common_required_amount;$('requiredMaterials').value=settings.required_materials.join(', ');$('entryDate').value=today();buildChecks();}
function buildChecks(selected=[]){$('materialChecks').innerHTML=settings.required_materials.map((m,i)=>`<label class="check"><input type="checkbox" data-mat="${esc(m)}" ${selected.includes(m)?'checked':''}><span>${esc(m)}</span></label>`).join('')||'<span class="muted">Set required materials above.</span>'}
function esc(s){return String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function populatePicker(){const q=($('studentSearch').value||'').toLowerCase();const list=students.filter(s=>`${s.roll_no} ${s.student_name}`.toLowerCase().includes(q));$('entryStudent').innerHTML=list.map(s=>`<option value="${s.student_id}">${esc(s.roll_no)} • ${esc(s.student_name)} — ${s.payment_status}</option>`).join(''); if(list.length)selectedEntryId=Number(list[0].student_id)}
function render(){
  const q=($('recordSearch').value||'').toLowerCase(), sf=$('statusFilter').value, mf=$('materialFilter').value;
  const rows=students.filter(s=>(`${s.roll_no} ${s.student_name}`.toLowerCase().includes(q))&&(sf==='all'||s.payment_status===sf)&&(mf==='all'||s.materials_received===Number(mf)));
  $('studentTable').innerHTML=rows.map(s=>{
    const statusClass=s.payment_status.toLowerCase().replace(/\s+/g,'-');
    const excess=s.excess_amount||0;
    return `<tr class="record-row ${excess>0?'is-exceeding':''}"><td><b>${esc(s.roll_no)}</b></td><td><div class="student-cell"><span class="avatar">${esc(s.student_name[0]||'?').toUpperCase()}</span><div><b>${esc(s.student_name)}</b><small>${s.payment_count} payment(s)</small></div></div></td><td>${money(s.required_amount)}</td><td class="paid">${money(s.amount_paid)}</td><td class="${s.remaining_amount?'balance':''}">${money(s.remaining_amount)}</td><td>${excess?`<span class="excess-amount">+${money(excess)}</span>`:'—'}</td><td><span class="pill mode">${esc(s.payment_mode)}</span></td><td><span class="pill ${statusClass}">${s.payment_status}</span></td><td><span class="mat-pill">${s.materials_received}/${s.materials_total}</span></td><td><button class="icon-btn" title="Edit" onclick="openEdit(${s.student_id})">✎</button></td></tr>`;
  }).join('')||'<tr><td colspan="10" class="empty">No matching students.</td></tr>';
  populatePicker();
  api('/api/summary').then(s=>{$('totalStudents').textContent=s.total_students;$('totalRequired').textContent=money(s.total_required);$('totalPaid').textContent=money(s.total_paid);$('totalPending').textContent=money(s.total_pending);$('upi').textContent=money(s.upi);$('cash').textContent=money(s.cash)});
}
$('studentSearch').oninput=populatePicker;$('recordSearch').oninput=render;$('statusFilter').onchange=render;$('materialFilter').onchange=render;
$('studentForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/students',{method:'POST',body:JSON.stringify({roll_no:$('rollNo').value,student_name:$('studentName').value})});e.target.reset();await load();toast('Student added');}catch(x){toast(x.message,false)}};
$('saveSettings').onclick=async()=>{try{settings=await api('/api/settings',{method:'POST',body:JSON.stringify({common_required_amount:$('commonAmount').value,required_materials:$('requiredMaterials').value})});await load();toast('Class settings saved');}catch(x){toast(x.message,false)}};
function updateAmountHint(){
  const student=students.find(s=>s.student_id===Number($('entryStudent').value));
  const amount=Number($('entryAmount').value||0);
  const hint=$('amountHint');
  if(!hint)return;
  if(!student || !amount){hint.textContent='';hint.className='amount-hint';return;}
  const projected=Number(student.amount_paid||0)+amount;
  if(projected>Number(student.required_amount||0)){
    hint.textContent=`Amount exceeding • ${money(projected-Number(student.required_amount||0))} over required`;
    hint.className='amount-hint exceed';
  }else{
    hint.textContent=`${money(Math.max(Number(student.required_amount||0)-projected,0))} remaining after this payment`;
    hint.className='amount-hint normal';
  }
}
$('entryAmount').oninput=updateAmountHint;
$('entryStudent').onchange=e=>{selectedEntryId=Number(e.target.value);updateAmountHint();};
$('saveEntry').onclick=async()=>{try{const id=selectedEntryId||Number($('entryStudent').value);if(!id)throw Error('Select a student first.');const amount=Number($('entryAmount').value||0);if(amount>0)await api(`/api/students/${id}/payments`,{method:'POST',body:JSON.stringify({amount_paid:amount,payment_mode:$('entryMode').value,transaction_details:$('entryDetails').value,payment_date:$('entryDate').value||today()})});const materials=[...document.querySelectorAll('#materialChecks input')].map(x=>({name:x.dataset.mat,status:x.checked?'Received':'Not Received'}));if(materials.length)await api(`/api/students/${id}/materials`,{method:'POST',body:JSON.stringify({materials,received_date:$('entryDate').value||today()})});$('entryAmount').value='';$('entryDetails').value='';$('amountHint').textContent='';await load();toast('Student record updated');}catch(x){toast(x.message,false)}};
async function openEdit(id){const s=students.find(x=>x.student_id===id);if(!s)return;$('editId').value=id;$('editTitle').textContent=`Edit • ${s.student_name}`;$('editRoll').value=s.roll_no;$('editName').value=s.student_name;$('editAmount').value='';$('editDate').value=today();$('editDetails').value='';$('editMaterials').innerHTML=settings.required_materials.map(m=>{const x=s.materials.find(a=>a.material_name===m);return `<label class="check"><input type="checkbox" data-editmat="${esc(m)}" ${x&&x.received_status==='Received'?'checked':''}><span>${esc(m)}</span></label>`}).join('');$('paymentHistory').innerHTML=s.materials.length||s.payment_count?`<div class="history-title">Current: ${money(s.amount_paid)} paid • ${money(s.remaining_amount)} remaining • ${s.materials_received}/${s.materials_total} materials received</div>`:'No previous activity';$('editModal').classList.add('open')}
function closeEdit(){$('editModal').classList.remove('open')};window.closeEdit=closeEdit;window.openEdit=openEdit;
$('saveEdit').onclick=async()=>{try{const id=$('editId').value;await api(`/api/students/${id}`,{method:'PUT',body:JSON.stringify({roll_no:$('editRoll').value,student_name:$('editName').value})});const amount=Number($('editAmount').value||0);if(amount>0)await api(`/api/students/${id}/payments`,{method:'POST',body:JSON.stringify({amount_paid:amount,payment_mode:$('editMode').value,transaction_details:$('editDetails').value,payment_date:$('editDate').value||today()})});const mats=[...document.querySelectorAll('#editMaterials input')].map(x=>({name:x.dataset.editmat,status:x.checked?'Received':'Not Received'}));if(mats.length)await api(`/api/students/${id}/materials`,{method:'POST',body:JSON.stringify({materials:mats,received_date:$('editDate').value||today()})});closeEdit();await load();toast('Changes saved');}catch(x){toast(x.message,false)}};
window.addEventListener('click',e=>{if(e.target===$('editModal'))closeEdit();if(e.target!==$('accountBtn')&&!$('accountMenu').contains(e.target))$('accountMenu').classList.remove('open')});
$('accountBtn').onclick=()=>$('accountMenu').classList.toggle('open');
$('logoutBtn').onclick=async()=>{await supabaseClient.auth.signOut();$('accountMenu').classList.remove('open');};
$('authSwitch').onclick=()=>setAuthMode(authMode==='login'?'signup':'login');
$('forgotBtn').onclick=async()=>{
  const email=$('authEmail').value.trim();
  if(!email){$('authMessage').textContent='Enter your email first.';return;}
  const {error}=await supabaseClient.auth.resetPasswordForEmail(email,{redirectTo:window.location.origin});
  $('authMessage').textContent=error?error.message:'Password reset email sent. Check your inbox.';
};
$('authForm').onsubmit=async e=>{
  e.preventDefault(); $('authSubmit').disabled=true; $('authMessage').textContent='';
  const email=$('authEmail').value.trim(), password=$('authPassword').value;
  let result;
  if(authMode==='signup') result=await supabaseClient.auth.signUp({email,password});
  else result=await supabaseClient.auth.signInWithPassword({email,password});
  $('authSubmit').disabled=false;
  if(result.error){$('authMessage').textContent=result.error.message;return;}
  if(authMode==='signup'&&!result.data.session){$('authMessage').textContent='Account created. Check your email to confirm it, then sign in.';}
};
$('reportBtn').onclick=async()=>{
  const btn=$('reportBtn');
  try{
    const {data:{session}}=await supabaseClient.auth.getSession();
    if(!session){showAuth('Please sign in to download your report.');return;}
    btn.disabled=true;btn.classList.add('loading');
    const r=await fetch('/report',{method:'GET',cache:'no-store',headers:{Authorization:`Bearer ${session.access_token}`,Accept:'application/pdf'}});
    if(!r.ok){const d=await r.json().catch(()=>({}));throw Error(d.error||'Could not create report.');}
    const blob=await r.blob();
    if(blob.size<100)throw Error('The PDF was empty. Please try again.');
    const url=URL.createObjectURL(blob), a=document.createElement('a');
    a.href=url;a.download=`student_report_${today()}.pdf`;a.style.display='none';
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1500);
    toast('PDF downloaded');
  }catch(e){toast(e.message||'Could not download the PDF.',false);}
  finally{btn.disabled=false;btn.classList.remove('loading');}
};
setAuthMode('login');initAuth();
