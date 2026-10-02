'use strict';
const $ = id => document.getElementById(id);
let user = null, csrf = '', tab = 'logs', offset = 0, stream = null, photo = null, photoURL = null;
let loading = false, generation = 0, cameraGeneration = 0, rows = [];
const limit = 50;
function notice(message, error = false) { $('notice').textContent = message; $('notice').classList.toggle('error', error); }
async function request(path, options = {}) {
  const headers = {...options.headers};
  if (csrf) headers['X-CSRF-Token'] = csrf;
  const response = await fetch(path, {...options, headers, credentials:'same-origin', signal:AbortSignal.timeout(20000)});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && user) lock();
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}). Check the form values.`);
  }
  return data;
}
async function api(path, options = {}) {
  if (!user) throw new Error('Sign in with your staff account first.');
  return request('/api/v1/admin/' + path, options);
}
function jsonOptions(method, data) { return {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}; }
function applyRole() {
  $('auth').classList.toggle('signed-in', Boolean(user));
  $('identity').textContent = user ? `${user.username} · ${user.role}` : '';
  $('enrollment-panel').hidden = !user || user.role === 'viewer';
  $('terminal-panel').hidden = !user || user.role !== 'owner';
  $('users-panel').hidden = !user || user.role !== 'owner';
  $('account-panel').hidden = !user;
  for (const name of ['users','audit']) document.querySelector(`[data-tab="${name}"]`).hidden = !user || user.role !== 'owner';
  document.querySelector('[data-tab="terminals"]').hidden = !user || user.role === 'viewer';
}
function clearData() { for (const id of ['total','present','absent','late']) $(id).textContent = '—'; rows = []; render(); }
function stopCamera() { cameraGeneration++; if (stream) stream.getTracks().forEach(t => t.stop()); stream = null; $('video').srcObject = null; $('video').hidden = true; $('capture').disabled = true; }
function setPhoto(file) {
  if (photoURL) URL.revokeObjectURL(photoURL);
  photo = file; photoURL = file ? URL.createObjectURL(file) : null;
  $('preview').hidden = !file;
  if (file) $('preview').src = photoURL; else $('preview').removeAttribute('src');
}
function lock() { generation++; user = null; csrf = ''; $('password').value = ''; stopCamera(); setPhoto(null); for(const id of ['enroll','terminal','new-user','reset-password','change-password']) $(id).reset(); tab='logs'; offset=0; applyRole(); clearData(); notice('Locked. Sign in with your staff account.'); }
function cell(tr, text, extra) { const td = document.createElement('td'); td.textContent = text ?? ''; if (extra) { const s = document.createElement('small'); s.textContent = extra; td.append(s); } tr.append(td); return td; }
function render() {
  const columns = tab === 'logs' ? ['Scan time','Student','Direction','Status','Review'] : tab === 'students' ? ['Student ID','Name','Phone','Actions'] : tab === 'terminals' ? ['Terminal','Location','Direction','State','Actions'] : tab === 'users' ? ['ID','Username','Role','State','Actions'] : ['Time','Action','Subject','Staff'];
  $('table-head').replaceChildren(); const head = document.createElement('tr');
  for (const name of columns) { const th = document.createElement('th'); th.textContent = name; head.append(th); } $('table-head').append(head);
  $('table-body').replaceChildren();
  for (const row of rows) {
    const tr = document.createElement('tr');
    if (tab === 'logs') { cell(tr,row.actual_entry,row.date); cell(tr,row.name,row.student_id); cell(tr,row.event_type,row.terminal_uuid); cell(tr,row.attendance); cell(tr,row.review_required ? 'Review needed' : '—').className = 'review'; }
    else if (tab === 'students') {
      cell(tr,row.student_id); cell(tr,row.name); cell(tr,row.phone_number || '—'); const td=cell(tr,'');
      if (user?.role === 'viewer') { $('table-body').append(tr); continue; }
      const b=document.createElement('button'); b.textContent='Delete'; b.className='danger';
      b.onclick=async()=>{if (!confirm(`Delete ${row.name}, their face templates and all attendance logs?`)) return; b.disabled=true; try {await api('students/'+row.internal_id,{method:'DELETE'}); await refresh(); notice('Student and associated records deleted.');}catch(e){notice(e.message,true);}finally{b.disabled=false;}};td.append(b);
    } else if (tab === 'terminals') {
      cell(tr,row.terminal_uuid);cell(tr,row.location_name);cell(tr,row.direction);cell(tr,row.active?'Active':'Revoked');const td=cell(tr,'');
      if(row.active && user?.role === 'owner'){const b=document.createElement('button');b.textContent='Revoke';b.className='danger';b.onclick=async()=>{if(!confirm(`Revoke ${row.terminal_uuid}? Pending uploads will pause.`))return;try{await api('terminals/'+encodeURIComponent(row.terminal_uuid),{method:'DELETE'});await refresh();}catch(e){notice(e.message,true);}};td.append(b);}
    }
    if (tab === 'users') {
      cell(tr,row.id);cell(tr,row.username);cell(tr,row.role);cell(tr,row.active?'Active':'Disabled');
      const td=cell(tr,'');const select=document.createElement('select');
      for(const role of ['viewer','operator','owner']){const option=document.createElement('option');option.value=role;option.textContent=role;option.selected=role===row.role;select.append(option);}
      const save=document.createElement('button');save.textContent='Save role';
      const toggle=document.createElement('button');toggle.textContent=row.active?'Disable':'Enable';
      async function update(data){try{await api('users/'+row.id,jsonOptions('PATCH',data));await refresh();notice('Account updated. Its sessions were revoked.');}catch(e){notice(e.message,true);}}
      save.onclick=()=>update({role:select.value});toggle.onclick=()=>update({active:!row.active});td.append(select,save,toggle);
    } else if(tab === 'audit') {cell(tr,new Date(row.occurred_at).toLocaleString());cell(tr,row.action);cell(tr,row.subject);cell(tr,row.actor_username || 'Server console / legacy');}
    $('table-body').append(tr);
  }
  if (!rows.length) {const tr=document.createElement('tr');const td=cell(tr,user?'No records on this page.':'Connect to view records.');td.colSpan=columns.length;$('table-body').append(tr);}
  $('page').textContent = `Page ${offset/limit+1}`; $('prev').disabled = offset===0 || tab==='terminals'; $('next').disabled = rows.length<limit || tab==='terminals';
}
async function refresh() {
  if (!user || loading) return;
  loading=true; const current=generation;
  try {
    const path=tab==='logs'?`attendance/logs?limit=${limit}&offset=${offset}${$('date').value?'&date='+$('date').value:''}`:tab==='students'?`students?limit=${limit}&offset=${offset}`:tab==='audit'?`audit?limit=${limit}&offset=${offset}`:tab;
    const [stats,data] = await Promise.all([api('dashboard-stats'),api(path)]);
    if(current!==generation)return;
    $('total').textContent=stats.total_students;$('present').textContent=stats.today_present;$('absent').textContent=stats.today_absent;$('late').textContent=stats.late_entries;
    rows=data;render();notice('Connected · Last refreshed '+new Date().toLocaleTimeString());
  } catch(e){if(current===generation){clearData();notice(e.message+' Data unavailable.',true);}}
  finally {loading=false; if(current!==generation && user) refresh();}
}
$('auth').onsubmit=async e=>{e.preventDefault();generation++;const credentials={username:$('username').value.trim(),password:$('password').value};$('password').value='';try{const session=await request('/api/v1/auth/login',jsonOptions('POST',credentials));user=session.user;csrf=session.csrf_token;applyRole();const cfg=await api('config');$('schedule').textContent=`Class schedule ${cfg.class_start}–${cfg.class_end} · ${cfg.timezone}`;await refresh();}catch(err){lock();notice(err.message,true);}finally{credentials.password='';}};
$('logout').onclick=async()=>{try{if(user)await request('/api/v1/auth/logout',{method:'POST'});lock();}catch(e){notice('Sign-out failed. Retry to revoke this session. '+e.message,true);}};
$('refresh').onclick=()=>refresh();
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;offset=0;generation++;rows=[];render();document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('selected',x===b));$('table-title').textContent=b.textContent;$('table-hint').textContent=tab==='logs'?'Gate events do not prove classroom attendance. Review flagged events before using them in reports.':tab==='users'?'Role and account changes revoke staff sessions. Keep at least one active owner.':tab==='audit'?'Recorded staff actions, ordered by time.':tab==='students'?'Registered students. Viewer accounts cannot access phone numbers.':'Registered terminal identities and directions.';$('date-control').hidden=tab!=='logs';refresh();});
$('date').onchange=()=>{offset=0;generation++;refresh();};$('prev').onclick=()=>{offset=Math.max(0,offset-limit);generation++;refresh();};$('next').onclick=()=>{offset+=limit;generation++;refresh();};
$('photo').onchange=e=>{const f=e.target.files[0];if(f&&(!['image/jpeg','image/png'].includes(f.type)||f.size>4*1024*1024)){e.target.value='';setPhoto(null);notice('Choose a JPEG or PNG up to 4 MiB.',true);return;}setPhoto(f||null);};
$('camera').onclick=async()=>{stopCamera();const current=cameraGeneration;try{const acquired=await navigator.mediaDevices.getUserMedia({video:{width:640,height:480},audio:false});if(current!==cameraGeneration){acquired.getTracks().forEach(t=>t.stop());return;}stream=acquired;$('video').hidden=false;$('video').srcObject=stream;$('capture').disabled=false;}catch(e){notice('Camera unavailable. Allow camera access on localhost or HTTPS.',true);}};
$('stop-camera').onclick=stopCamera;
$('capture').onclick=()=>{const v=$('video');if(!stream||!v.videoWidth){notice('Wait for the camera image.',true);return;}const c=$('canvas');c.width=v.videoWidth;c.height=v.videoHeight;c.getContext('2d').drawImage(v,0,0);c.toBlob(blob=>{if(blob){setPhoto(new File([blob],'capture.jpg',{type:'image/jpeg'}));$('photo').value='';}stopCamera();},'image/jpeg',.9);};
$('enroll').onsubmit=async e=>{e.preventDefault();if(!photo){notice('Choose or capture a photo.',true);return;}const b=e.target.querySelector('button[type=submit]');b.disabled=true;try{const data=new FormData(e.target);data.set('consent','true');data.set('file',photo);await api('register-student',{method:'POST',body:data});e.target.reset();setPhoto(null);stopCamera();await refresh();notice('Student enrolled successfully.');}catch(err){notice(err.message,true);}finally{b.disabled=false;}};
$('terminal').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{await api('register-terminal',{method:'POST',body:new FormData(e.target)});e.target.reset();await refresh();notice('Terminal configured. Keep its token in the terminal’s private environment file.');}catch(err){notice(err.message,true);}finally{b.disabled=false;}};
window.addEventListener('pagehide',()=>{stopCamera();if(photoURL)URL.revokeObjectURL(photoURL);});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopCamera();});
$('new-user').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));try{await api('users',jsonOptions('POST',data));e.target.reset();await refresh();notice('Staff account created.');}catch(err){notice(err.message,true);}finally{data.password='';e.target.elements.password.value='';}};
$('reset-password').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));try{await api(`users/${data.user_id}/reset-password`,jsonOptions('POST',{new_password:data.new_password}));e.target.reset();notice('Password reset. Sessions revoked.');}catch(err){notice(err.message,true);}finally{data.new_password='';e.target.elements.new_password.value='';}};
$('change-password').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));try{await request('/api/v1/auth/password',jsonOptions('POST',data));lock();notice('Password changed. Sign in again.');}catch(err){notice(err.message,true);}finally{e.target.reset();}};
setInterval(()=>{if(!document.hidden)refresh();},15000);applyRole();render();
