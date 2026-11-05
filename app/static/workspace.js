'use strict';
const $=id=>document.getElementById(id), statuses=['Not tested','Passed','Failed','Blocked','Skipped'];
const uuid=()=>crypto.randomUUID();
let task=null,currentSet=null,cases=null,accounts=[],draftKey=uuid(),generationKey=null,baseline='',gen,busy=false,searchRevision=0,deletedAccountIds=[],removedSends={},foldedCases={};
// Unsaved work is kept per task for this session only. Saving stays an
// explicit act: switching tasks parks the draft, it does not write to the DB.
const drafts=new Map();const DRAFT_LIMIT=20;
function stash(){if(!dirty()){drafts.delete(draftKey);return;}
drafts.set(draftKey,{task,settings:gen.snapshot(),mentionEdits:JSON.parse(JSON.stringify(mentionEdits)),cases:JSON.parse(JSON.stringify(cases||[])),accounts:JSON.parse(JSON.stringify(accounts)),deletedAccountIds:[...deletedAccountIds],removedSends:JSON.parse(JSON.stringify(removedSends)),currentSet,generationKey,baseline,savedAt:Date.now()});
while(drafts.size>DRAFT_LIMIT)drafts.delete(drafts.keys().next().value);}
function unstash(key){return drafts.get(key)||null;}
const frame=$('generator');
// Keep the sticky sidebar below the notice, including wrapped messages.
const noticeObserver=new ResizeObserver(()=>document.documentElement.style.setProperty('--notice-height',`${$('notice').getBoundingClientRect().height}px`));
noticeObserver.observe($('notice'));
const generatorReady=new Promise(resolve=>{const ready=()=>{if(frame.contentWindow.qaGenerator)resolve(frame.contentWindow.qaGenerator);};frame.addEventListener('load',ready);ready();});
function notice(message,error=false){$('notice').textContent=message;$('notice').classList.toggle('error',error);}
function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
function button(text,handler,style='secondary'){const b=el('button',text,style);b.type='button';b.onclick=handler;return b;}
function field(label,value,type='text'){const l=el('label',label),i=el(type==='textarea'?'textarea':'input');if(type!=='textarea')i.type=type;i.value=value??'';l.append(i);return [l,i];}
const date=value=>new Date(value).toLocaleString('ru-RU');
// A 500 from Starlette is plain text, not JSON: parse defensively so the user
// sees the HTTP status instead of "Unexpected token 'I', Internal S...".
async function api(path,method='GET',body){const r=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});if(r.status===204)return null;const raw=await r.text();let data=null;try{data=raw?JSON.parse(raw):null;}catch{data=null;}if(!r.ok){const detail=data&&data.detail;throw Error(typeof detail==='string'?detail:(detail?JSON.stringify(detail):`Ошибка ${r.status} ${r.statusText}`.trim()));}return data;}
const setPath=()=>`/api/tasks/${task.id}/sets/${currentSet.id}`;
function payload(){const mentions=mentionValues();return {task_id:task?.id,client_key:draftKey,jira_id:$('jiraId').value,title:$('taskTitle').value,settings:{...gen.snapshot(),mention_edits:{[mentionRegion()]:mentions}},deleted_account_ids:deletedAccountIds,set_id:currentSet?.id,generation_key:generationKey,test_accounts:accounts.map(({id,name,account_id,login,password,kind})=>({id,name,account_id,login,password,kind})),cases:cases?.map(({id,client_key,title,text,comment,request_text,status,qa_comment,bug_links,test_account_id})=>({id,client_key,title,text,comment,request_text,status,qa_comment,bug_links,test_account_id,removed_slack_sends:removedSends[client_key]||[]}))??null};}
const signature=()=>gen?JSON.stringify(payload()):'';
const dirty=()=>signature()!==baseline;
let markedSignature='';function mark(){const current=signature();if(current===baseline){notice('Изменения совпадают с сохранёнными.');return;}if(current===markedSignature)return;markedSignature=current;notice('Есть несохранённые изменения · нажмите «Сохранить».');}
async function action(fn){if(busy)return;busy=true;$('workspace').inert=true;try{await fn();}catch(e){notice(e.message,true);}finally{busy=false;$('workspace').inert=false;}}
async function listTasks(){const revision=++searchRevision,items=await api('/api/tasks?q='+encodeURIComponent($('search').value)+($('onlyActive').checked?'&active=true':''));if(revision!==searchRevision)return;$('tasks').replaceChildren();for(const item of items){const b=button('',()=>action(()=>selectTask(item.id)),'task');b.dataset.id=item.id;b.dataset.status=item.status||'active';b.setAttribute('aria-current',String(task?.id===item.id));if(item.jira_id)b.append(el('strong',item.jira_id));b.append(el('span',item.title||'Без названия'));if(item.status==='done')b.append(el('em','done'));
// Drawn from state, not patched afterwards: the list is rebuilt after every save.
const count=taskReplies[String(item.id)];if(count){b.dataset.replies='new';b.append(el('span',count>1?`+${count}`:'новый ответ','replies-dot'));}
$('tasks').append(b);}}function adoptSet(value){currentSet=value;generationKey=value?.generation_key||null;removedSends={};replyBaseline={};caseReplies={};cases=value?value.cases.map(c=>({...c,client_key:c.client_key||uuid()})):null;for(const c of cases||[])if(c.id)setReplyBaseline(c);linkAccounts();renderMentions();renderCases();restoreTaskReplies();if(value&&value.id){startReplyStream();}else{stopReplyStream();}}
async function listSets(){return task?await api(`/api/tasks/${task.id}/sets`):[];}
function showTask(){ $('jiraId').value=task?.jira_id||'';$('taskTitle').value=task?.title||'';$('deleteTask').hidden=!task;const toggle=$('toggleStatus');toggle.hidden=!task;const done=task?.status==='done';toggle.textContent='Статус: '+(task?.status||'active');toggle.classList.toggle('done',!!done);toggle.setAttribute('aria-pressed',String(!!done));toggle.title=done?'Вернуть в активные':'Пометить как done';$('dates').textContent=task?`Изменена ${date(task.updated_at)}`:'Черновик · ещё не сохранён';gen.lockRegion(!!task?.region);}
async function selectTask(id){stash();const key='task:'+id;const saved=unstash(key);
task=await api(`/api/tasks/${id}`);draftKey=task.client_key||uuid();
const draft=saved||unstash(draftKey);
if(draft){restoreDraft(draft);await listTasks();notice(`Открыта ${name()} · восстановлены несохранённые изменения.`);return;}
accounts=task.test_accounts||[];deletedAccountIds=[];removedSends={};gen.restore(task.settings);restoreMentions(task.settings);gen.setAccountOptions(accounts);showTask();const items=await listSets();adoptSet(items.length?await api(`/api/tasks/${id}/sets/${items[0].id}`):null);renderAccounts();baseline=signature();markedSignature='';await listTasks();notice(`Открыта ${name()}`);}
// The generator stores the licence of the task; WebView cases ship that build.
function currentLicence(){const licence=gen&&gen.snapshot?gen.snapshot().fields.license:'';return ['com','pinco','zazino'].includes(licence)?licence:'';}
// Only a case that runs in the WebView shell needs the APK; the licence
// alone would attach a build to native and HPP cases too.
function isWebviewCase(record){return /^Platform:\s*WebView\s*$/im.test(String(record&&record.text||''));}
function caseLicence(record){const licence=isWebviewCase(record)?currentLicence():'';return licence||null;}
function name(){return task?.jira_id||task?.title||'Без названия';}
function restoreDraft(draft){task=draft.task||task;draftKey=draft.task?.client_key||draftKey;accounts=draft.accounts;deletedAccountIds=draft.deletedAccountIds;removedSends=draft.removedSends;currentSet=draft.currentSet;generationKey=draft.generationKey;mentionEdits=draft.mentionEdits;gen.restore(draft.settings);restoreMentions(draft.settings);gen.setAccountOptions(accounts);showTask();cases=draft.cases;linkAccounts();renderMentions();renderCases();renderAccounts();listSets();baseline=draft.baseline;markedSignature='';
// A restored draft keeps the same set, so replies must keep arriving too.
// The reply baseline is NOT reset: existing answers stay history, not news.
for(const c of cases||[])if(c.id&&!(c.id in replyBaseline))setReplyBaseline(c);
restoreCaseReplies();restoreTaskReplies();
if(currentSet&&currentSet.id){startReplyStream();}else{stopReplyStream();}}
async function newDraft(check=true){stash();task=null;accounts=[];deletedAccountIds=[];draftKey=uuid();gen.restore();mentionEdits={};renderMentions();accounts=await gen.loadAccounts();showTask();adoptSet(null);renderAccounts();await listSets();baseline=signature();markedSignature='';await listTasks();notice('Черновик готов. Заполните параметры и сгенерируйте кейсы.');}
async function saveWork(){importAccounts();const result=await api('/api/tasks/save','POST',payload());task=result.task;accounts=task.test_accounts;deletedAccountIds=[];gen.setAccountOptions(accounts);adoptSet(result.set);showTask();renderAccounts();await listSets();baseline=signature();markedSignature='';drafts.delete(draftKey);await listTasks();notice('Сохранено: настройки, аккаунты и текущие кейсы.');}
function renderCasePickers(){for(const card of $('cases').children){const id=card.dataset.caseId;const record=(cases||[]).find(c=>String(c.id||c.client_key)===id);const select=card.querySelector('select[aria-label="Тестовый аккаунт"]');if(!record||!select)continue;const current=record.test_account_id||'';select.replaceChildren();const none=el('option','Без назначения');none.value='';select.append(none);for(const a of accounts){const o=el('option',`${a.name} · ${a.account_id||a.login||'без ID'}`);o.value=a.id;select.append(o);}select.value=accounts.some(a=>a.id===current)?current:'';}}
function applyAccount(record,account){if(!account)return;
// An account with blank fields must not blank the case: only real values
// are written, the rest of the header stays as the tester left it.
const values=[[/^(AccountID|ID акаунта|ID аккаунта):/i,'AccountID',account.account_id],[/^(login|логін|Логин):/i,'login',account.login],[/^(Password|Пароль):/i,'Password',account.password]]
.filter(([, ,value])=>String(value??'').trim());
const parts=record.text.split('\n\n'),lines=parts[0].split('\n');
for(const [pattern,label,value] of values){const index=lines.findIndex(line=>pattern.test(line));
if(index>=0)lines[index]=lines[index].split(':')[0]+': '+value;else lines.push(label+': '+value);}
parts[0]=lines.join('\n');record.text=parts.join('\n\n');}
function readAccountFromText(text){const lines=String(text||'').split('\n');const pick=re=>{const line=lines.find(l=>re.test(l));return line?line.slice(line.indexOf(':')+1).trim():'';};return {account_id:pick(/^(AccountID|ID акаунта|ID аккаунта):/i),login:pick(/^(login|логін|Логин):/i),password:pick(/^(Password|Пароль):/i)};}
// Older cases stored the credentials in their text but no account link, so
// the picker opened on "Без назначения" and switching changed nothing.
// Attach the account whose credentials the header already shows.
function linkAccounts(){const link=(record)=>{if(record.test_account_id)return;const creds=readAccountFromText(record.text);if(!creds.login&&!creds.account_id)return;const hit=accounts.find(a=>a.login===creds.login&&a.account_id===creds.account_id);if(hit)record.test_account_id=hit.id;};for(const c of cases||[])link(c);}
function importAccounts(){const f=gen.snapshot().fields,result={};for(const kind of ['main','usd']){if(kind==='usd'&&f.license!=='com')continue;const values=kind==='main'?[f.account,f.login,f.password]:[f.usdAccount,f.usdLogin,f.usdPassword];if(!values.some(Boolean))continue;let account=accounts.find(a=>a.account_id===values[0]&&a.login===values[1]&&a.password===values[2]);if(!account){account={id:uuid(),name:values[1]||values[0]||(kind==='main'?'Основной аккаунт':'USD аккаунт'),kind,account_id:values[0]||'',login:values[1]||'',password:values[2]||''};accounts.push(account);}result[kind]=account;}return result;}
function generated(_,values){const defaults=importAccounts();generationKey=uuid();cases=values.map(c=>{const a=defaults[c.account_kind];const record={...c,client_key:uuid(),status:'Not tested',qa_comment:'',bug_links:[],test_account_id:a?.id||null};applyAccount(record,a);return record;});renderAccounts();renderCases();mark();}
function renderAccounts(){ gen.setAccountOptions(accounts);if($('accounts').children.length||accounts.length)renderCasePickers();$('accounts').replaceChildren();for(const account of accounts){const row=el('div',undefined,'account-row');for(const [key,label,type] of [['name','Имя','text'],['account_id','ID аккаунта','text'],['login','Логин','text'],['password','Пароль','text']]){const [l,i]=field(label,account[key],type);i.maxLength=key==='name'?200:4000;i.oninput=()=>{const previous={...account};account[key]=i.value;gen.syncAccount(previous,account);gen.setAccountOptions(accounts);for(const c of cases||[])if(c.test_account_id===account.id)applyAccount(c,account);renderCases();mark();};row.append(l);}row.append(button('Удалить юзера',()=>{if(!confirm('Удалить пользователя из общего списка региона? Назначения во всех задачах региона будут сняты; текст старых кейсов останется.'))return;deletedAccountIds.push(account.id);accounts=accounts.filter(a=>a.id!==account.id);
const fields=gen.snapshot().fields;for(const kind of ['main','usd']){const ids=kind==='main'?['account','login','password']:['usdAccount','usdLogin','usdPassword'];if([account.account_id,account.login,account.password].every((v,i)=>fields[ids[i]]===v))gen.syncAccount(account,{account_id:'',login:'',password:''});}for(const c of cases||[])if(c.test_account_id===account.id)c.test_account_id=null;renderAccounts();renderCases();mark();},'danger'));$('accounts').append(row);}if(!accounts.length)$('accounts').append(el('p','Аккаунтов пока нет. Добавьте юзера или заполните данные в генераторе.','muted'));}

// Mentions live in the workspace now: they belong to the region of the open
// task, not to the generator form, and the iframe clipped them off-screen.
// `directory` holds the shared per-region list (slack_people); `mentionEdits`
// is the per-task working copy. Editing one never touches the other.
let directory={},mentionEdits={},slackPeople={};
const mentionRegion=()=>currentSet?.region||task?.region||'TR';
const mentionValues=()=>(mentionEdits[mentionRegion()]||[]).map(v=>v.trim()).filter(Boolean);
function mentionId(value){const m=String(value||'').match(/(?:^|\/team\/|^@|<@)([UW][A-Z0-9]{2,})/);return m?m[1]:null;}
function mentionLabel(value){const id=mentionId(value);return (id&&slackPeople[id])||value;}
function renderMentions(){const region=mentionRegion(),list=$('mentionList');list.replaceChildren();
if(!Object.hasOwn(mentionEdits,region))mentionEdits[region]=[...(directory[region]||[])];
mentionEdits[region]=mentionEdits[region].filter(v=>typeof v==='string');
mentionEdits[region].forEach((value,index)=>{
const row=el('div',undefined,'mention-row');
const input=el('input');input.type='text';input.value=value;input.maxLength=300;
input.placeholder='Ссылка на профиль, U0123456789 или @username';
input.setAttribute('aria-label','Человек для тега '+(index+1));
input.oninput=()=>{mentionEdits[region][index]=input.value;mark();};
input.onblur=()=>resolveMention(region,index,input,label);
const label=el('span',mentionLabel(value),'mention-name');
const remove=button('Исключить',()=>{mentionEdits[region].splice(index,1);renderMentions();mark();});
row.append(input,label,remove);list.append(row);});
$('mentionStatus').textContent=mentionEdits[region].length?'':'Никто не будет отмечен.';}
async function resolveMention(region,index,input,label){const value=input.value.trim();if(!value)return;try{const data=await api('/api/slack/people','POST',{entries:[value]});const person=data.people&&data.people[0];if(!person)return;slackPeople={...slackPeople,...(data.names||{})};if(person.id!==value){mentionEdits[region][index]=person.id;input.value=person.id;}label.textContent=person.label;mark();
// A person who is not in the shared directory yet: offer to remember them.
if(!Object.keys(directory).length||!Object.values(directory).flat().some(v=>mentionId(v)===person.id)){
if(confirm(`Добавить «${person.label}» в общий список региона ${region}?\n\nOK — сохранить в справочнике (доступен во всех задачах региона).\nОтмена — использовать только в этой задаче.`)){
await api('/api/slack/people/directory','POST',{entry:person.id,region,name:person.name||''});
await loadMentions();}
}
}catch(e){/* keep the typed value; sending explains the problem */}}
/** Load the shared directory for the current region plus every known name. */
async function loadMentions(){const region=mentionRegion();
try{const data=await api('/api/slack/people?region='+encodeURIComponent(region));
directory={[region]:(data.people||[]).map(p=>p.id)};
slackPeople={...(data.names||{}),...slackPeople};}
catch(e){$('mentionStatus').textContent='Не удалось загрузить список людей. Обновите страницу.';}
renderMentions();}
/** Apply the per-region mentions stored with a task's settings. */
function restoreMentions(settings){mentionEdits=JSON.parse(JSON.stringify((settings&&settings.mention_edits)||{}));renderMentions();}
function renderCounts(){$('counts').replaceChildren(...statuses.map(s=>el('span',`${s}: ${(cases||[]).filter(c=>c.status===s).length}`)));}
function renderCases(){ $('cases').replaceChildren();renderCounts();$('sendSet').disabled=!cases?.length;$('setInfo').textContent=currentSet?`Сохранённый набор · ${date(currentSet.created_at)}. Изменения применяются кнопкой «Сохранить».`:'Изменения кейсов сохраняются кнопкой «Сохранить».';for(const record of cases||[]){const card=el('article',undefined,'case');card.dataset.status=record.status;card.dataset.caseId=record.id||record.client_key;const heading=el('h3',record.title),body=el('pre',record.text);heading.setAttribute('aria-label','Название кейса');body.setAttribute('aria-label','Текст кейса');const [rl,request]=field('Обращение в Slack',record.request_text,'textarea'),[cl,comment]=field('Дополнительные инструкции для Slack',record.comment,'textarea');request.readOnly=comment.readOnly=true;request.maxLength=2000;comment.maxLength=20000;
const edit=button('Редактировать кейс и текст для Slack',()=>{const editing=edit.getAttribute('aria-pressed')!=='true';edit.setAttribute('aria-pressed',String(editing));edit.textContent=editing?'Готово':'Редактировать кейс и текст для Slack';heading.contentEditable=body.contentEditable=editing?'plaintext-only':'false';request.readOnly=comment.readOnly=!editing;if(editing)body.focus();});edit.setAttribute('aria-pressed','false');
// Long cases push everything else off the screen; collapse the text, the Slack
// request and the extra instructions, keeping the controls at hand.
const key=String(record.id||record.client_key);
const collapse=button('Свернуть кейс',()=>{const folded=collapse.dataset.folded!=='true';collapse.dataset.folded=String(folded);collapse.textContent=folded?'Развернуть кейс':'Свернуть кейс';long.hidden=folded;if(folded)foldedCases[key]=true;else delete foldedCases[key];});
const actions=el('div',undefined,'row');actions.append(edit,collapse,button('Удалить кейс',()=>{if(!confirm('Удалить кейс? Удаление из БД применится после «Сохранить».'))return;cases=cases.filter(c=>c!==record);renderCases();mark();},'danger'),button('Отправить в Slack',()=>send([record.client_key])));
const label=el('label','Тестовый аккаунт'),select=el('select');select.setAttribute('aria-label','Тестовый аккаунт');const none=el('option','Без назначения');none.value='';select.append(none);for(const a of accounts){const o=el('option',`${a.name} · ${a.account_id||a.login||'без ID'}`);o.value=a.id;select.append(o);}select.value=record.test_account_id||'';select.onchange=()=>{const chosen=accounts.find(a=>a.id===select.value)||null;if(select.value&&!chosen){notice('Аккаунт не найден в списке региона. Обновите задачу.',true);return;}record.test_account_id=chosen?chosen.id:null;if(chosen)applyAccount(record,chosen);body.textContent=record.text;mark();};label.append(select);
const statusLabel=el('label','Статус'),status=el('select');statuses.forEach(s=>status.append(el('option',s)));status.value=record.status;status.onchange=()=>{record.status=status.value;card.dataset.status=record.status;renderCounts();applyFilter();mark();};statusLabel.append(status);
const [ql,qa]=field('Личный комментарий',record.qa_comment,'textarea');qa.maxLength=20000;
heading.oninput=()=>{record.title=heading.innerText;mark();};body.oninput=()=>{record.text=body.innerText;mark();};request.oninput=()=>{record.request_text=request.value;mark();};comment.oninput=()=>{record.comment=comment.value;mark();};qa.oninput=()=>{record.qa_comment=qa.value;mark();};
const apk=el('div',undefined,'apk-note');renderApkNote(apk,record);const history=el('div',undefined,'slack-history');renderHistory(record,history);
const long=el('div',undefined,'case-long');long.append(body,rl,cl);
// A card rebuilt by renderCases() must stay folded if the operator folded it.
if(foldedCases[key]){collapse.dataset.folded='true';collapse.textContent='Развернуть кейс';long.hidden=true;}
else collapse.dataset.folded='false';
card.append(actions,label,heading,long,statusLabel,ql,apk,history);$('cases').append(card);}applyFilter();restoreCaseReplies();}
function applyFilter(){for(const card of $('cases').children)card.hidden=!!$('statusFilter').value&&card.dataset.status!==$('statusFilter').value;}
// A WebView case carries the build of its licence; say which one, and when
// it was uploaded, before the tester sends anything.
async function renderApkNote(host,record){host.replaceChildren();const licence=caseLicence(record);if(!licence){host.hidden=true;return;}host.hidden=false;try{const info=await api('/api/webview/apk-for/'+licence);if(!info.available){host.append(el('span',`WebView APK (${licence}): сборка не загружена — файл не прикрепится.`));host.classList.add('warn');return;}host.classList.remove('warn');host.append(el('span',`К сообщению будет прикреплён файл: ${info.filename} · сборка от ${date(info.uploaded_at)}`));}catch(e){host.textContent='Не удалось узнать сборку APK: '+e.message;}}
function renderHistory(record,host){
  host.replaceChildren();
  const gone=removedSends[record.client_key]||[];
  const sends=(record.slack_sends||[]).filter(d=>!gone.includes(d.id));
  if(!sends.length){renderReplies(record,host);return;}
  // Newest first: a case can be sent many times and the latest send is what matters.
  const list=el('div',undefined,'sends');
  list.append(el('small',sends.length===1?'1 отправка':'Отправок: '+sends.length));
  for(const delivery of sends){
    const row=el('p',date(delivery.sent_at)+' · ');
    if(delivery.permalink){
      const a=el('a','Открыть в Slack');
      a.href=delivery.permalink;a.target='_blank';a.rel='noopener noreferrer';
      row.append(a);
    }else{
      row.append(el('span','Ссылка недоступна. '));
      row.append(button('Получить ссылку',()=>action(async()=>{
        await api(`${setPath()}/cases/${record.id}/slack-sends/${delivery.id}/permalink`,'POST');
        await refreshHistory();
        notice('Обновлена история ссылок. Сообщения повторно не отправлялись.');
      })));
    }
    row.append(button('Удалить',()=>action(async()=>{
      if(!confirm('Удалить сообщение и весь тред из Slack? Восстановить не получится.'))return;
      try{
        const deleted=await api(`${setPath()}/cases/${record.id}/slack-sends/${delivery.id}`,'DELETE');
        notice(`Удалено из Slack сообщений: ${deleted.deleted_messages}.`);
      }catch(e){
        notice(e.message,true);
        return;
      }
      removedSends[record.client_key]=[...(removedSends[record.client_key]||[]),delivery.id];
      await refreshHistory();
      mark();
    }),'danger'));
    list.append(row);
  }
  host.append(list);
  renderReplies(record,host);
}
function renderReplies(record,host){
  const replies=record.slack_replies||[];
  if(!replies.length)return;
  const box=el('div',undefined,'slack-replies');
  const head=el('div',undefined,'slack-replies-head');
  head.append(el('strong','Ответы в треде · '+replies.length));
  // The only control that changes the read state. Clicking anywhere else in the
  // card must leave it alone: the operator may be editing the case text.
  const read=hasNews(record);
  const toggle=button(
    read?'Прочитано':'Отметить как непрочитанное',
    ()=>read?markRepliesRead(record):markRepliesUnread(record),
    'replies-toggle',
  );
  // Only the unread state is highlighted; a read thread keeps the plain chip.
  toggle.dataset.state=read?'unread':'read';
  head.append(toggle);
  box.append(head);
  for(const reply of replies){
    const row=el('p',date(reply.received_at)+' · '+(reply.author_name||reply.author_id||'Slack')+': ');
    row.append(el('span',reply.text||'(без текста)'));
    box.append(row);
  }
  host.append(box);
}
// Replies known when the set was opened. Anything at or below this ts is
// history, not news: reloading or saving must not light up a case.
let replyBaseline={};
function setReplyBaseline(record){const last=(record.slack_replies||[]).reduce((max,r)=>Math.max(max,parseFloat(r.ts)||0),0);replyBaseline[record.id]=last;}
function isNewReply(record,reply){const known=replyBaseline[record.id]||0;return (parseFloat(reply&&reply.ts)||0)>known;}
async function refreshHistory(){if(!currentSet)return;const result=await api(setPath());for(const c of cases||[]){c.slack_sends=result.cases.find(r=>r.id===c.id)?.slack_sends||[];const host=document.querySelector(`[data-case-id="${c.id}"] .slack-history`);if(host)renderHistory(c,host);}await refreshReplies();restoreTaskReplies();}
async function refreshReplies(){for(const c of cases||[]){if(!c.id)continue;try{const replies=await api(`${setPath()}/cases/${c.id}/slack-replies`);const fresh=replies.filter(r=>isNewReply(c,r));c.slack_replies=replies;if(fresh.length){setReplyBaseline(c);markNewReplies(c,fresh.length);}else if(!(c.id in replyBaseline)){setReplyBaseline(c);}const host=document.querySelector(`[data-case-id="${c.id}"] .slack-history`);if(host)renderHistory(c,host);}catch(e){}}}
// Replies arrive without a page reload. The backend pushes them over SSE the
// moment Slack is stored; a slow timer is only a safety net for a dropped
// connection, so a reply never waits for a poll tick.
let replyTimer=null,replyStream=null;
// Replies seen per task while it is open, so the sidebar entry can glow too.
let taskReplies={};
/** Replies seen per case, so a card keeps its badge when renderCases() runs again. */
let caseReplies={};
/** True while a case carries replies the operator has not acknowledged yet. */
function hasNews(record){return !!caseReplies[String(record.id)];}
function startReplyPolling(){if(replyTimer)return;replyTimer=setInterval(()=>{if(document.hidden||!currentSet||busy)return;if(replyStream&&replyStream.readyState===EventSource.OPEN)return;refreshReplies().catch(()=>{});},120000);}
function stopReplyStream(){if(replyStream){replyStream.close();replyStream=null;}}
function startReplyStream(){stopReplyStream();if(!currentSet||typeof EventSource==='undefined')return;
replyStream=new EventSource(`${setPath()}/stream`);
replyStream.onmessage=event=>{let data;try{data=JSON.parse(event.data);}catch{return;}if(data.type!=='reply')return;
const caseIds=(data.case_ids||[]).map(Number);
for(const c of cases||[]){if(!caseIds.includes(Number(c.id)))continue;const entry={ts:data.ts,text:data.text,author_id:data.author,received_at:data.received_at};const known=replyBaseline[c.id]||0;c.slack_replies=[...(c.slack_replies||[]),entry];if((parseFloat(entry.ts)||0)>known){replyBaseline[c.id]=parseFloat(entry.ts)||0;markNewReplies(c,1);}const host=document.querySelector(`[data-case-id="${c.id}"] .slack-history`);if(host)renderHistory(c,host);}}
replyStream.onerror=()=>{/* EventSource reconnects on its own; the timer covers downtime. */};
}
function markNewReplies(record,fresh){const id=String(record.id);caseReplies[id]=(caseReplies[id]||0)+fresh;const card=document.querySelector(`[data-case-id="${record.id}"]`);paintCaseReplies(record,card,fresh);
// The «Прочитано» action lives inside the thread block, so redraw it here too:
// the badge alone would leave the operator without a way to dismiss it.
const host=card?.querySelector('.slack-history');if(host)renderHistory(record,host);
// The sidebar must say the same thing: a reply belongs to the open task too.
// The id comes from the payload first: `task` is still null while `selectTask`
// awaits its request, and a reply can land exactly in that window.
const taskId=currentTaskId();  if(taskId){const key=String(taskId);taskReplies[key]=(taskReplies[key]||0)+fresh;
    // `listTasks()` is async: a request started before this point would rebuild
    // `#tasks` and drop the dot, so re-render from the saved counts afterwards.
    markTaskReplies(key,taskReplies[key]);
    listTasks();}
notice(`Новые ответы в Slack: ${fresh}.`);}
/** The id of the task the open set belongs to, even if `task` is stale. */
function currentTaskId(){
  // `currentSet` comes straight from the API and always carries its task id,
  // so it survives a reload or a draft restore where `task` may be stale.
  if(currentSet?.task_id!=null)return String(currentSet.task_id);
  if(task?.id!=null)return String(task.id);
  const node=document.querySelector('#tasks .task[aria-current="true"]');
  return node?.dataset.id||null;
}
function paintCaseReplies(record,card,fresh){if(!card)return;const count=fresh??caseReplies[String(record.id)];if(!count)return;card.dataset.replies='new';const heading=card.querySelector('h3');if(heading&&!heading.querySelector('.replies-badge')){const badge=el('span',(count>1?`+${count}`:'новый ответ')+' · Slack','replies-badge');heading.append(badge);}}/** Repaint case badges lost when renderCases() rebuilt the cards. */
function restoreCaseReplies(){for(const c of cases||[]){if(!c.id)continue;const card=document.querySelector(`[data-case-id="${c.id}"]`);paintCaseReplies(c,card);}}
function markTaskReplies(taskId,count){const node=document.querySelector(`#tasks .task[data-id="${taskId}"]`);if(!node)return;node.dataset.replies='new';let dot=node.querySelector('.replies-dot');if(!dot){dot=el('span','','replies-dot');node.append(dot);}dot.textContent=count>1?`+${count}`:'новый ответ';}
/** Paint every remembered task mark; call after the list is rebuilt. */
function restoreTaskReplies(){for(const [key,count] of Object.entries(taskReplies)){if(count)markTaskReplies(key,count);}}
function clearTaskReplies(taskId){const key=String(taskId);delete taskReplies[key];const node=document.querySelector(`#tasks .task[data-id="${taskId}"]`);if(!node)return;delete node.dataset.replies;node.querySelector('.replies-dot')?.remove();}
function clearRepliesMark(record){delete caseReplies[String(record.id)];const card=document.querySelector(`[data-case-id="${record.id}"]`);if(card){delete card.dataset.replies;card.querySelector('.replies-badge')?.remove();}}
/** Mark every reply of one case as read: badge, sidebar mark and the button. */
function markRepliesRead(record){
  clearRepliesMark(record);
  // The task entry only stays lit while some case still has news.
  const taskId=currentTaskId();
  if(taskId&&!Object.keys(caseReplies).length)clearTaskReplies(taskId);
  const host=document.querySelector(`[data-case-id="${record.id}"] .slack-history`);
  if(host)renderHistory(record,host);
}
/** Put the news mark back: the thread still has replies worth another look. */
function markRepliesUnread(record){
  caseReplies[String(record.id)]=1;
  const card=document.querySelector(`[data-case-id="${record.id}"]`);
  paintCaseReplies(record,card,1);
  const taskId=currentTaskId();
  if(taskId){
    taskReplies[String(taskId)]=(taskReplies[String(taskId)]||0)+1;
    markTaskReplies(String(taskId),taskReplies[String(taskId)]);
  }
  const host=card?.querySelector('.slack-history');
  if(host)renderHistory(record,host);
}
/**
 * Header of a manually added case, built by the generator from its own tables.
 * The workspace cannot compute currency or platform: they come from the region
 * and wallet data that only the generator page holds.
 */
function caseHeader(){
// Only the request header: the generator also appends the step list and the
// video request, which the tester writes by hand for a case added here.
const generated=(gen&&gen.caseText?gen.caseText():'').split('\n\n')[0].trimEnd();
return (generated||'Cashdesk payment request:')+'\n\n\n';
}
function addCase(){
if(!gen)return;
const record={client_key:uuid(),title:'Новый кейс',text:caseHeader(),comment:'',request_text:'',status:'Not tested',qa_comment:'',bug_links:[],test_account_id:null};
cases=[...(cases||[]),record];
renderCases();mark();
const cards=$('cases').children;const node=cards[cards.length-1];if(node){node.scrollIntoView({block:'center'});const heading=node.querySelector('h3');if(heading)heading.focus();}
notice('Кейс добавлен. Текст взят из генератора; шаги и остальное заполните вручную.');}
function send(keys){action(async()=>{await saveWork();const selected=cases.filter(c=>keys.includes(c.client_key));try{notice('Отправка в Slack…');const result=await api('/slack/send-cases','POST',{region:currentSet.region,operation:currentSet.operation,mention_users:mentionValues(),cases:selected.map(c=>({case_ids:[c.id],title:c.title,text:c.text,comment:c.comment,request_text:c.request_text,licence:caseLicence(c)}))});notice(`В Slack отправлено кейсов: ${result.sent}.`);}catch(e){notice(e.message+' Автоматического повтора отправки не будет. Проверьте историю перед новой отправкой.',true);}finally{await refreshHistory();}});}
$('saveWork').onclick=$('saveCurrent').onclick=()=>action(saveWork);$('newTask').onclick=()=>action(()=>newDraft());$('addAccount').onclick=()=>{accounts.push({id:uuid(),name:'Юзер '+(accounts.length+1),account_id:'',login:'',password:'',kind:'main'});renderAccounts();mark();};$('sendSet').onclick=()=>send((cases||[]).map(c=>c.client_key));$('addCase').onclick=()=>addCase();$('statusFilter').onchange=applyFilter;$('search').oninput=()=>listTasks().catch(e=>notice(e.message,true));$('onlyActive').onchange=()=>listTasks().catch(e=>notice(e.message,true));$('toggleStatus').onclick=()=>action(async()=>{if(!task)return;const result=await api(`/api/tasks/${task.id}/status`,'POST',{});task.status=result.status;showTask();await listTasks();notice(result.status==='done'?'Задача помечена как done.':'Задача снова активна.');});for(const id of ['jiraId','taskTitle'])$(id).oninput=mark;
$('addMention').onclick=()=>{const region=mentionRegion();if(!Object.hasOwn(mentionEdits,region))mentionEdits[region]=[];mentionEdits[region].push('');renderMentions();mark();};
$('resetMentions').onclick=()=>{const region=mentionRegion();mentionEdits[region]=[...(directory[region]||[])];renderMentions();mark();};
$('deleteTask').onclick=()=>action(async()=>{if(!confirm('Удалить задачу со всеми кейсами без возможности восстановления?'))return;await api(`/api/tasks/${task.id}`,'DELETE');await newDraft(false);});

async function slackStatus(){const status=await api('/api/slack-status');$('slackStatus').textContent=status.connected?'Slack подключён':'Slack не подключён';}
window.addEventListener('focus',()=>slackStatus().catch(()=>{}));document.addEventListener('input',()=>mark());document.addEventListener('change',()=>mark());window.addEventListener('beforeunload',e=>{if(busy||(gen&&dirty())){e.preventDefault();e.returnValue='';}});

// --- WebView APK library ---------------------------------------------------
const LICENCE_NAMES={com:'COM',pinco:'Pinco',zazino:'Zazino'};
// The panel shows the result itself; the status line is only for problems.
function apkProblem(message){const box=$('apkStatus');box.textContent=message;box.hidden=!message;}
async function loadApks(){const data=await api('/api/webview/apks');const host=$('apkList');host.replaceChildren();
for(const row of data.licences){const box=el('div',undefined,'apk-row');box.append(el('strong',LICENCE_NAMES[row.licence]||row.licence));
if(row.uploaded_at){const link=el('a','Скачать '+row.filename);link.href='/api/webview/apks/'+row.licence;
box.append(el('span',' · '+date(row.uploaded_at)+' · '+Math.round((row.size_bytes||0)/1024)+' КБ '),link);
box.append(button('Удалить',()=>action(async()=>{if(!confirm('Удалить сборку '+(LICENCE_NAMES[row.licence]||row.licence)+'? Тестировщики не смогут её скачать.'))return;
await api('/api/webview/apks/'+row.licence,'DELETE');await loadApks();$('apkStatus').textContent='Сборка удалена.';}),'danger'));}
else box.append(el('span',' · сборка не загружена','muted'));host.append(box);}}
async function loadApkPeople(){const data=await api('/api/webview/people');const host=$('apkPeople');host.replaceChildren();
host.append(el('p','Кого тегать в канале WebView:','muted'));
for(const person of data.people){const row=el('div',undefined,'row');row.append(el('span',(person.name||person.id)+' · '+person.id));
row.append(button('Убрать',()=>action(async()=>{await api('/api/webview/people/'+person.id,'DELETE');await loadApkPeople();}),'danger'));host.append(row);}
const [label,input]=field('Добавить человека (ссылка, ID или @username)','');const add=button('Добавить',()=>action(async()=>{
const value=input.value.trim();if(!value)return;await api('/api/webview/people','POST',{entry:value,name:''});input.value='';await loadApkPeople();}),'secondary');
host.append(label,add);}
async function uploadApk(){const file=$('apkFile').files[0];if(!file){apkProblem('Выберите файл APK.');return;}
const body=new FormData();body.append('licence',$('apkLicence').value);body.append('file',file);
const response=await fetch('/api/webview/apks',{method:'POST',body});if(!response.ok){const data=await response.json();throw Error(typeof data.detail==='string'?data.detail:'Не удалось загрузить файл');}
$('apkFile').value='';await loadApks();apkProblem('');}
async function requestBuild(){const licences=[...$('requestLicences').querySelectorAll('input[type="checkbox"]:checked')].map(box=>box.value);
if(!licences.length){apkProblem('Выберите хотя бы одну лицензию.');return;}
const result=await api('/api/webview/request','POST',{licences});
apkProblem('');}
// Two screens share one layout: the task workspace and the WebView builds.
function showScreen(which){const web=which==='webview';$('tasksBlock').hidden=web;$('mainBlock').hidden=web;$('webviewBlock').hidden=!web;$('openWebview').hidden=web;document.querySelector('.layout').classList.toggle('webview-mode',web);}
$('openWebview').onclick=()=>{showScreen('webview');loadApks().catch(e=>apkProblem(e.message));loadApkPeople().catch(()=>{});};
$('closeWebview').onclick=()=>showScreen('tasks');
$('apkUpload').onclick=()=>action(uploadApk);$('requestBuild').onclick=()=>action(requestBuild);
(async()=>{gen=await generatorReady;await gen.ready;gen.configure({beforeGenerate:()=>!cases?.length||confirm('Заменить текущие кейсы новой генерацией? Изменения будут записаны по кнопке «Сохранить».'),onGenerated:generated,beforeRegionChange:()=>!cases?.length||confirm('Сменить регион и сбросить сгенерированные кейсы?'),onRegionChange:()=>action(async()=>{accounts=await gen.loadAccounts();deletedAccountIds=[];adoptSet(null);renderAccounts();await loadMentions();notice('Загружены пользователи выбранного региона.');})});await newDraft(false);await loadMentions();await slackStatus();startReplyPolling();})().catch(e=>notice(e.message,true));
// Opening a case clears its "new replies" badge; the replies stay in the list.
$('cases').addEventListener('click',event=>{
  // The read state belongs to its own button: a click on the card may be an
  // edit, a status change or a scroll, and none of them mean «я посмотрел».
});
