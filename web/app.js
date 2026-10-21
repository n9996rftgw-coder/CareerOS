'use strict';

let state = null;
let page = (location.hash || '#today').slice(1);
let query = '';
let filter = '';
let busy = false;
const pages = {today:'Today',applications:'Applications',network:'Network',targets:'Targets',evidence:'Evidence & drafts'};
const $ = (selector) => document.querySelector(selector);
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const label = value => String(value || 'Not recorded').replace(/_/g, ' ');
const dateLabel = value => value ? new Date(value + (String(value).length === 10 ? 'T12:00:00' : '')).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : 'Not recorded';
const tag = (value, cls='') => `<span class="tag ${cls}">${escape(label(value))}</span>`;
const btn = (text, action, id='', cls='button small') => `<button class="${cls}" data-action="${action}" data-id="${escape(id)}">${text}</button>`;
const safeURL = value => { try { const u = new URL(value); return ['https:','http:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };

async function load(quiet=false) {
  try {
    const response = await fetch('/api/state');
    if (!response.ok) throw new Error('The local workspace could not be opened.');
    state = await response.json();
    render();
    if (quiet) toast('Local snapshot refreshed.');
  } catch (error) {
    if (!state) $('#main').innerHTML = `<div class="notice amber">${escape(error.message)} Reopen CareerOS to try again.</div>`;
    else toast(error.message);
  }
}

function navigate(next) {
  page = pages[next] ? next : 'today'; query = ''; filter = '';
  location.hash = page;
  render();
}

function header(title, subtitle, actions='', eyebrow='YOUR CAREER WORKSPACE') {
  return `<div class="page-head"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p>${subtitle}</p></div><div class="head-actions">${actions}</div></div>`;
}

function integrationNotice() {
  const c = state.integrations || {};
  const sheet = c.google_sheets || c.sheets || c.sheet || c;
  const url = safeURL(sheet.url || sheet.sheet_url || sheet.spreadsheet_url || c.sheet_url || c.spreadsheet_url || '');
  const synced = sheet.last_synced || sheet.synced_at || c.last_synced || c.synced_at;
  const desc = synced ? ` Last synced ${escape(dateLabel(synced))}.` : ' No connector sync time has been recorded.';
  return `<div class="notice"><strong>Local review snapshot.</strong>${desc} Chat updates the live Google Sheet through its connector. Local edits need reconciliation; they do not sync automatically.${url ? ` <a href="${escape(url)}" target="_blank" rel="noopener noreferrer">Open live Google Sheet ↗</a>` : ''}</div>`;
}

function render() {
  if (!state) return;
  if (!pages[page]) page = 'today';
  document.querySelectorAll('[data-page]').forEach(node => { const active = node.dataset.page === page; node.classList.toggle('active',active); node.setAttribute('aria-current',active?'page':'false'); });
  $('#breadcrumb').textContent = `Workspace / ${pages[page]}`;
  $('#due-count').textContent = state.today_items.length || '';
  ['applications','network','targets'].forEach(t => $(`#${t==='applications'?'apps':t}-count`).textContent = state.tables[t].length);
  const views = {today:renderToday,applications:renderApplications,network:renderNetwork,targets:renderTargets,evidence:renderEvidence};
  $('#main').innerHTML = views[page]();
  bindFilters();
}

function renderToday() {
  const s = state.stats;
  const targets = state.tables.targets;
  const applications = state.tables.applications;
  const due = state.today_items;
  const greeting = 'Your next chapter, in focus.';
  const metric = (title, value, note) => `<div class="metric"><div class="metric-label">${title}<span>↗</span></div><div class="metric-value">${value}</div><small>${note}</small></div>`;
  return header(greeting, 'A clear view of the search. Keep the next step specific, and the evidence close.', btn('+ Add a role','add-application','','button primary'), dateLabel(state.today).toUpperCase()) + integrationNotice() +
    `<div class="metric-grid">${metric('Applications logged', applications.length, 'In this local register')}${metric('Applications sent', s.sent, 'Recorded as applied or beyond')}${metric('Active conversations',state.tables.network.filter(c=>['replied','meeting','warm'].includes(c.Status)).length,'Replied, meeting or warm contacts')}${metric('Target organisations',targets.length,'Organisations to explore')}</div>`+
    `<div class="content-grid"><div><section class="panel"><div class="panel-head"><div><h2>Your next moves</h2><p>Dated deadlines and follow-ups from your register</p></div>${tag(`${due.length} due`)}</div>${due.length?due.map(item=>`<div class="due-item"><div class="step">${item[0]==='deadline'?'◷':'↗'}</div><div><small>${escape(label(item[0]))} · ${dateLabel(item[1])}</small><p>${escape(item[2])}</p></div></div>`).join(''):`<div class="empty compact"><div class="empty-symbol">✓</div><h3>No dated tasks due.</h3><p>Add a role, deadline or contact follow-up to bring the next action here.</p></div>`}</section>`+
    `<section class="panel"><div class="panel-head"><div><h2>Move the search forward</h2><p>A practical starting point</p></div></div><div class="next-card"><div class="step">01</div><div><h3>Bring in a real job description</h3><p>Log the role, then create a CV draft from the evidence store. Gaps remain visible.</p>${btn('Add your first role →','add-application','','subtle-link')}</div></div><div class="next-card"><div class="step">02</div><div><h3>Build the relationship alongside the application</h3><p>Add the person, their organisation and the next action. Record outreach only after you send it.</p>${btn('Add a contact →','add-network','','subtle-link')}</div></div><div class="next-card"><div class="step">03</div><div><h3>Keep one clear next step</h3><p>A deadline or follow-up date turns an open opportunity into a dated action.</p>${btn('Review applications →','view-applications','','subtle-link')}</div></div></section>`+
    `<section class="panel"><div class="panel-head"><div><h2>Your target list</h2><p>Supplied organisations · no live vacancies implied</p></div>${btn('View all →','view-targets','','subtle-link')}</div><div class="panel-body targets-mini">${targets.slice(0,8).map(t=>`<div class="target-mini"><div class="org-mark">${initials(t.Organisation)}</div><div>${escape(t.Organisation)}<span>${escape(t.Type || 'Type not recorded')}</span></div></div>`).join('')}</div></section></div><div>`+
    `<div class="goal-card"><p class="eyebrow">THE DIRECTION</p><h2>Think like a marketer.<br>Execute like a producer.</h2><p>Full-time London.<br>Senior Executive / Manager boundary.<br>Creative Marketing & Content Strategy.</p></div><section class="panel"><div class="panel-head"><h2>Quick actions</h2></div>${btn('Add an application <span>＋</span>','add-application','','quick-action')}${btn('Add a contact <span>＋</span>','add-network','','quick-action')}${btn('Review evidence & drafts <span>→</span>','view-evidence','','quick-action')}${btn('Export local tracker <span>↗</span>','export','','quick-action')}</section><div class="notice plain"><strong>A fresh working register.</strong><br>${escape(state.history_notice)}</div></div></div>`;
}

function initials(text) { return escape((text || '').replace(/[^\p{L}\p{N}\s]/gu,'').split(/\s+/).filter(Boolean).slice(0,2).map(s=>s[0]).join('').toUpperCase()); }
function filtered(table) { return state.tables[table].filter(r=>Object.values(r).join(' ').toLowerCase().includes(query.toLowerCase()) && (!filter || (table==='targets'?r.Type:r.Status)===filter)); }
function toolbar(table, choices) {
  return `<div class="toolbar"><div class="search-wrap"><span>⌕</span><label class="sr-only" for="search">Search ${table}</label><input class="search" id="search" type="search" placeholder="Search ${table==='network'?'people, organisations or notes':table==='targets'?'organisations or notes':'roles, companies or notes'}…" value="${escape(query)}"></div><label class="sr-only" for="filter">Filter ${table}</label><select id="filter"><option value="">All ${table==='targets'?'types':'statuses'}</option>${choices.map(v=>`<option value="${escape(v)}" ${filter===v?'selected':''}>${escape(label(v))}</option>`).join('')}</select><span class="muted">${filtered(table).length} records</span></div>`;
}
function bindFilters() { if ($('#search')) $('#search').addEventListener('input',event=>{query=event.target.value; const start=event.target.selectionStart;render();$('#search').focus();$('#search').setSelectionRange(start,start);}); if ($('#filter')) $('#filter').addEventListener('change',event=>{filter=event.target.value;render();}); }

function renderApplications() {
  const rows = filtered('applications');
  return header('The application register.','One record per company and role. Draft, review, send, then record the outcome.',btn('Export tracker','export')+btn('+ Add a role','add-application','','button primary'))+integrationNotice()+toolbar('applications',state.choices.Status)+
    `<section class="panel">${rows.length?`<div class="table-wrap"><table><thead><tr><th>Company & role</th><th>Status</th><th>Deadline / follow-up</th><th>Next step</th><th>Actions</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${escape(r.Company)}</strong>${escape(r.Role)}<small>${escape(r.ID)}${r.Lane?' · '+escape(r.Lane):''}</small></td><td>${tag(r.Status,['applied','screening','interview_1','interview_2','offer'].includes(r.Status)?'green':'draft')}<small>${escape(r.Source || 'Source not recorded')}</small></td><td>${r.Deadline?dateLabel(r.Deadline):'—'}<small>${r['Follow-up Date']?'Follow-up '+dateLabel(r['Follow-up Date']):'No follow-up dated'}</small></td><td>${escape(r['Next Best Action']||'Not recorded')}<small>${r['CV Version']?'CV draft available':'No CV draft yet'}</small></td><td><div class="row-actions">${btn('Details','edit-application',r.ID,'text-link')}${btn('Status','status',r.ID,'text-link')}${btn('CV draft','draft',r.ID,'text-link')}${r['CV Version']?btn('Interview prep','prep',r.ID,'text-link'):''}</div></td></tr>`).join('')}</tbody></table></div>`:`<div class="empty"><div class="empty-symbol">▤</div><h3>${query||filter?'No matching roles.':'Your next role starts here.'}</h3><p>${query||filter?'Try another search or status filter.':'Add a real opportunity and its job description. Your CV draft will use only the evidence in your store.'}</p>${btn('+ Add a role','add-application','','button primary')}</div>`}</section><div class="notice plain">${escape(state.history_notice)} Keyword coverage in engine reviews is a local text comparison; it is not an ATS score or a hiring prediction.</div>`;
}

function renderNetwork() {
  const rows = filtered('network');
  return header('People open doors.','Keep the context, the conversation and the next step in one place.',btn('+ Add a contact','add-network','','button primary'))+integrationNotice()+toolbar('network',state.choices.NetworkStatus)+
    `<section class="panel">${rows.length?`<div class="table-wrap"><table><thead><tr><th>Person</th><th>Connection</th><th>Status</th><th>Next action</th><th>Actions</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${escape(r.Name)}</strong>${escape(r.Company)}<small>${escape(r['Their Role']||r.ID)}</small></td><td>${escape(r.Type||'Not recorded')}<small>${escape(r['How Met']||'Context not recorded')}</small></td><td>${tag(r.Status)}<small>${r['Last Contact']?'Last contact '+dateLabel(r['Last Contact']):'No contact recorded'}</small></td><td>${escape(r['Next Action']||'Not recorded')}<small>${r['Follow-up Date']?dateLabel(r['Follow-up Date']):'No follow-up dated'}</small></td><td><div class="row-actions">${btn('Details','edit-network',r.ID,'text-link')}${btn('Log outreach','outreach',r.ID,'text-link')}${btn('Create brief','brief',r.ID,'text-link')}</div></td></tr>`).join('')}</tbody></table></div>`:`<div class="empty"><div class="empty-symbol">♧</div><h3>${query||filter?'No matching people.':'Start with someone you know.'}</h3><p>A careers fair conversation, a recruiter or a former colleague. Add the real details you have; leave unknowns blank.</p>${btn('+ Add a contact','add-network','','button primary')}</div>`}</section><div class="notice plain">Outreach actions create a brief or record a message you have already sent. CareerOS does not send messages.</div>`;
}

function renderTargets() {
  const rows = filtered('targets');
  return header('Be deliberate about where.','Your supplied target organisations. Research and current vacancies need checking.',btn('+ Add a target','add-targets','','button primary'))+integrationNotice()+toolbar('targets',state.choices.TargetType)+
    `<div class="cards">${rows.map(r=>`<article class="target-card"><div class="org-mark">${initials(r.Organisation)}</div><h3>${escape(r.Organisation)}</h3><div>${tag(r.Type)} ${r.Priority?tag(r.Priority):''}</div><p>${escape(r['Why Them']||r.Notes||'Add a specific reason to target this organisation.')}</p>${r['Why Them']&&r.Notes?`<p>${escape(r.Notes)}</p>`:''}<div class="row-actions">${btn('Details','edit-targets',r.ID,'text-link')}${btn('Research template','research',r.ID,'text-link')}${safeURL(r['Careers URL'])?`<a class="text-link" href="${escape(safeURL(r['Careers URL']))}" target="_blank" rel="noopener noreferrer">Careers ↗</a>`:''}</div></article>`).join('')}</div>${!rows.length?'<div class="empty"><h3>No matching targets.</h3><p>Try another search or add an organisation.</p></div>':''}<div class="notice plain">Target notes are supplied context. Dates and vacancies in them have not been checked live by this local dashboard. Research templates start empty and need sources.</div>`;
}

function renderEvidence() {
  const roles = state.roles;
  const proofs = roles.reduce((sum,r)=>sum+(r.bullets||[]).length,0);
  const checks = state.checks || [];
  return header('Your work is the foundation.','Keep the full record. Select the evidence each opportunity needs. Review every outgoing draft.',btn('Export tracker','export'))+integrationNotice()+
    `<div class="notice">${escape(state.evidence_note)} The evidence store is read-only in this review workspace.</div><div class="evidence-stats"><span><strong>${roles.length}</strong> role entries</span><span><strong>${proofs}</strong> supplied proof points</span><span><strong>${state.summaries.length}</strong> draft summaries</span></div><div class="content-grid"><div><section class="panel"><div class="panel-head"><div><h2>Work experience store</h2><p>Original wording · full context retained</p></div></div>${roles.map(r=>`<details><summary><strong>${escape(r.employer)}</strong>${r.lineage?' '+escape(r.lineage):''}<small>${escape(r.start)} – ${escape(r.end)}</small><div class="date-label">${escape(r.title)} · ${escape(r.location||'')}</div></summary><div class="role-content">${r.flag?`<div class="notice amber">${escape(r.flag)}</div>`:''}${(r.bullets||[]).map(b=>`<div class="proof">${tag(b.status==='confirmed'?'Supplied as confirmed':(b.status||'draft'),b.status==='confirmed'?'':'draft')}<p>${escape(b.text)}</p><div class="proof-meta">${escape(b.id)}${b.number_note?' · Figure context: '+escape(b.number_note):''}${b.flag?' · Flag: '+escape(b.flag):''}${b.public==='pending'?' · Public use pending approval':''}</div></div>`).join('')}</div></details>`).join('')}</section><section class="panel"><div class="panel-head"><div><h2>Summary drafts</h2><p>Humanise the selected summary before sending</p></div></div><div class="panel-body">${state.summaries.map(s=>`<div class="summary-card"><h3>${escape(label(s.id))} ${tag('Draft · review required','draft')}</h3><p>${escape(s.text)}</p></div>`).join('')}</div></section></div><div><section class="panel"><div class="panel-head"><div><h2>Files & outputs</h2><p>Local drafts, review notes and exports</p></div></div><div class="panel-body">${state.artifacts.length?state.artifacts.map(f=>`<div class="file-row"><div><strong>${escape(f.name)}</strong><small>${escape(f.path)} · ${dateLabel(f.modified)}</small></div><a class="text-link" href="${escape(f.url)}" download>Download</a></div>`).join(''):'<p class="form-intro">No generated drafts yet. Add a role and its job description to create one.</p>'}</div></section><section class="panel"><div class="panel-head"><div><h2>Review notes</h2><p>Checks are prompts for review, not source verification</p></div></div><div class="panel-body">${checks.length?checks.map(c=>`<div class="check">${tag(c.level,c.level==='FAIL'?'fail':c.level==='WARN'?'warn':'')}<span>${escape(c.message)}</span></div>`).join(''):'<p class="form-intro">No machine-checkable issues returned.</p>'}</div></section></div></div>`;
}

function toast(message) { $('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.remove('show'),6000); }
function openDialog(title, body, eyebrow='LOCAL SNAPSHOT') { $('#dialog-title').textContent=title;$('#dialog-eyebrow').textContent=eyebrow;$('#dialog-body').innerHTML=body;if(!$('#dialog').open)$('#dialog').showModal(); }
function getRow(table,id) { return state.tables[table].find(r=>r.ID===id); }
function selectOptions(field, table) { const mapping={Status:table==='network'?'NetworkStatus':'Status',Type:table==='network'?'ContactType':'TargetType'}; return state.choices[mapping[field]||field]; }
function fieldHTML(field, value='', table='', required=false, readonly=false) {
  const choices=selectOptions(field,table), name=escape(field);
  const full=['Notes','Why Them','Next Best Action','Next Action','Assets Sent'].includes(field);
  const isDate=/Date$/.test(field)||['Deadline','Last Checked','Last Contact'].includes(field);
  const labelText=field==='Fit %'?'Text keyword coverage % (engine output)':field;
  let input;
  if(choices) input=`<select id="field-${name}" name="${name}" ${required?'required':''}><option value="">Not recorded</option>${choices.map(v=>`<option ${v===value?'selected':''} value="${escape(v)}">${escape(label(v))}</option>`).join('')}</select>`;
  else if(full) input=`<textarea id="field-${name}" name="${name}" rows="3">${escape(value)}</textarea>`;
  else input=`<input id="field-${name}" name="${name}" type="${isDate?'date':field==='Email'?'email':'text'}" value="${escape(value)}" ${required?'required':''} ${readonly?'readonly':''}>`;
  return `<div class="field ${full?'full':''}"><label for="field-${name}">${escape(labelText)}${required?' *':''}</label>${input}</div>`;
}

function editForm(table,id='') {
  const row = getRow(table,id)||{};
  const required={applications:['Company','Role'],network:['Name','Company'],targets:['Organisation']}[table];
  const main={applications:['Company','Role','Source','JD Link','Deadline','Lane','Level','Target ID','Next Best Action','Notes'],network:['Name','Company','Their Role','Type','How Met','LinkedIn','Email','Status','Next Action','Follow-up Date','Notes'],targets:['Organisation','Type','Lane','Priority','Careers URL','Why Them','Notes']}[table];
  const auto=['ID','Date Added','Last Status Change','First Response Date','First Interview Date','Fit %','Verdict','CV Version'];
  if(table==='applications')auto.push('Status');
  const more=state.fields[table].filter(f=>!main.includes(f)&&!auto.includes(f));
  const titles={applications:'application',network:'contact',targets:'target'};
  openDialog(`${id?'Update':'Add'} ${titles[table]}`,`<p class="form-intro">These changes are saved locally and need reconciliation with your live Google Sheet. Leave unknown details blank.${id?' Existing identity fields stay fixed; corrections can be noted below.':''}</p><form id="record-form"><div class="form-grid">${main.map(f=>fieldHTML(f,row[f],table,required.includes(f),!!id&&required.includes(f))).join('')}</div>${more.length?`<details class="form-expand"><summary>More details & linked records</summary><div class="form-grid">${more.map(f=>fieldHTML(f,row[f],table)).join('')}</div></details>`:''}<div class="form-error" id="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button type="submit" class="button primary">Save ${titles[table]}</button></div></form>`);
  $('#record-form').addEventListener('submit',async event=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.target));if(table==='applications'&&!id)data.Status='shortlisted';await submitForm(table,data);});
}

function statusForm(id) {
  const row=getRow('applications',id);
  openDialog('Update application status',`<p class="form-intro">${escape(row.Company)} · ${escape(row.Role)}. Record what has happened; this does not submit an application.</p><form id="status-form"><div class="form-grid">${fieldHTML('Status',row.Status,'applications',true)}<div class="field"><label for="status-date">Date it happened *</label><input id="status-date" type="date" name="on" value="${state.today}" max="${state.today}" required></div>${fieldHTML('Notes','','applications')}</div><div class="form-error" id="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button type="submit" class="button primary">Record status</button></div></form>`);
  $('#status-form').addEventListener('submit',async event=>{event.preventDefault();const f=Object.fromEntries(new FormData(event.target));await submitForm('status',{id,status:f.Status,notes:f.Notes,on:f.on});});
}

function outreachForm(id) {
  const row=getRow('network',id);
  openDialog('Record a conversation',`<p class="form-intro">${escape(row.Name)} · ${escape(row.Company)}. Record a message you already sent or received. Nothing is sent from this workspace.</p><form id="outreach-form"><div class="form-grid"><div class="field"><label for="event-date">Date it happened *</label><input id="event-date" type="date" name="event_date" value="${state.today}" max="${state.today}" required></div>${fieldHTML('Channel',row.Channel,'network')}<div class="field full"><label for="sent">What was sent or received *</label><textarea id="sent" name="sent" rows="3" placeholder="For example: CV version, a specific idea, or a short note on the reply" required></textarea><small>Describe the actual message or assets. This creates a dated record.</small></div><div class="field full"><label for="next-action">Next action</label><input id="next-action" name="next_action" value="${escape(row['Next Action'])}"></div></div><label class="checkbox"><input type="checkbox" name="replied">This was a reply from the contact</label>${row['Assets Sent']?`<div class="notice"><strong>Already recorded</strong><br>${escape(row['Assets Sent'])}</div>`:''}<div class="form-error" id="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button type="submit" class="button primary">Record conversation</button></div></form>`);
  $('#outreach-form').addEventListener('submit',async event=>{event.preventDefault();const f=Object.fromEntries(new FormData(event.target));await submitForm('outreach',{id,event_date:f.event_date,channel:f.Channel,sent:f.sent,next_action:f.next_action,replied:f.replied==='on'});});
}

function draftForm(id) {
  const row=getRow('applications',id);
  openDialog('Create a CV draft',`<p class="form-intro">${escape(row.Company)} · ${escape(row.Role)}. Paste the full job description. It is saved before drafting. The engine selects supplied evidence and writes a gap review.</p><form id="draft-form"><div class="field"><label for="jd-text">Job description *</label><textarea id="jd-text" name="jd_text" rows="13" required placeholder="Paste the real job description here…"></textarea></div><div class="notice amber">Draft for your review. Check evidence, gaps and page layout, then humanise the summary. Text keyword coverage is not an ATS score. No application is sent.</div><div class="form-error" id="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">Cancel</button><button type="submit" class="button primary">Save JD & create draft</button></div></form>`);
  $('#draft-form').addEventListener('submit',async event=>{event.preventDefault();await submitForm('draft',{id,jd_text:new FormData(event.target).get('jd_text')},true);});
}

async function api(action,payload) {
  const response=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-CareerOS-Token':state.token},body:JSON.stringify(payload)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'The action could not be completed.');return result;
}
async function submitForm(action,payload,showFiles=false) {
  if(busy)return;busy=true;const button=$('#dialog button[type="submit"]');const text=button.textContent;button.disabled=true;button.textContent=showFiles?'Creating draft…':'Saving…';$('#form-error').textContent='';
  try {const result=await api(action,payload);await load();if(showFiles)showResult(result);else{$('#dialog').close();toast(result.message);}}
  catch(error){$('#form-error').textContent=error.message;}
  finally{busy=false;if(button.isConnected){button.disabled=false;button.textContent=text;}}
}
function showResult(result) {
  const files=state.artifacts.filter(f=>f.path.startsWith('outputs/')).slice(0,8);
  const fileList=files.length?'<div class="notice plain">Download the draft and read its review before using it.</div>'+files.map(f=>`<div class="file-row"><div><strong>${escape(f.name)}</strong><small>${escape(f.path)}</small></div><a class="text-link" href="${escape(f.url)}" download>Download</a></div>`).join(''):'';
  openDialog('Ready for your review',`<div class="result"><p>${escape(result.message)}</p>${result.details?`<details><summary>Drafting details</summary><pre>${escape(result.details)}</pre></details>`:''}</div>${fileList}<div class="form-actions"><button class="button primary" data-action="view-evidence">View all evidence & drafts</button></div>`);
}
async function simpleAction(action,id) {
  if(busy)return;busy=true;
  if(action==='research') {
    openDialog('Create a research template',`<p class="form-intro">This creates an empty, local research file for ${escape(getRow('targets',id).Organisation)}. It does not research the company or check vacancies. Add dated sources before using any facts.</p><div class="form-error" id="form-error"></div><div class="form-actions"><button class="button" data-action="close">Cancel</button><button class="button primary" data-action="confirm-research" data-id="${escape(id)}">Create template</button></div>`);busy=false;return;
  }
  toast(action==='export'?'Building the local workbook…':'Preparing a review draft…');
  try {const result=await api(action,{id});await load();toast(result.message);if(result.url){const a=document.createElement('a');a.href=result.url;a.download='';document.body.appendChild(a);a.click();a.remove();}else showResult(result);}
  catch(error){toast(error.message);}finally{busy=false;}
}

document.addEventListener('click',async event=>{
  const nav=event.target.closest('[data-page]');if(nav){navigate(nav.dataset.page);return;}
  const actionEl=event.target.closest('[data-action]');if(!actionEl)return;
  const action=actionEl.dataset.action,id=actionEl.dataset.id;
  if(action==='close'){$('#dialog').close();return;}
  if(action.startsWith('view-')){$('#dialog').close();navigate(action.slice(5));return;}
  if(action.startsWith('add-')){const table=action.slice(4)==='application'?'applications':action.slice(4);editForm(table);return;}
  if(action.startsWith('edit-')){const table=action.slice(5)==='application'?'applications':action.slice(5);editForm(table,id);return;}
  if(action==='status')return statusForm(id);
  if(action==='outreach')return outreachForm(id);
  if(action==='draft')return draftForm(id);
  if(action==='confirm-research') { actionEl.disabled=true;try{const result=await api('research',{id});await load();$('#dialog').close();toast(result.message);navigate('evidence');}catch(error){$('#form-error').textContent=error.message;actionEl.disabled=false;}return; }
  if(['export','brief','prep','research'].includes(action))await simpleAction(action,id);
});
$('#close-dialog').addEventListener('click',()=>$('#dialog').close());
$('#refresh').addEventListener('click',()=>load(true));
window.addEventListener('hashchange',()=>{page=location.hash.slice(1)||'today';query='';filter='';render();});
load();
