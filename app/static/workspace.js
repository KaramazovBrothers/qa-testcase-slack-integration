'use strict';
const $=id=>document.getElementById(id);
const statuses=['Not tested','Passed','Failed','Blocked','Skipped'];
let task=null,currentSet=null,settingsBaseline='',resultBaseline='',searchRevision=0;
const dirtyCases=new Map();
const frame=$('generator');
const generatorReady=new Promise(resolve=>{
 const ready=()=>{if(frame.contentWindow.qaGenerator)resolve(frame.contentWindow.qaGenerator);};
 frame.addEventListener('load',ready);ready();
});
function notice(message,error=false){$('notice').textContent=message;$('notice').classList.toggle('error',error);}
async function api(path,method='GET',body){
 const response=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
 if(response.status===204)return null;
 const data=await response.json();
 if(!response.ok){const detail=data.detail;throw new Error(typeof detail==='string'?detail:JSON.stringify(detail));}
 return data;
}
const taskPath=()=>`/api/tasks/${task.id}`;
const setPath=()=>`${taskPath()}/sets/${currentSet.id}`;
function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
function formValue(form){return Object.fromEntries(new FormData(form));}
function date(value){return new Date(value).toLocaleString('ru-RU');}
let actionQueue=Promise.resolve();
let pendingActions=0;
function action(fn){
 pendingActions++;
 actionQueue=actionQueue.then(fn).catch(error=>notice(error.message,true)).finally(()=>pendingActions--);
 return actionQueue;
}
async function listTasks(){
 const revision=++searchRevision;
 const items=await api('/api/tasks?q='+encodeURIComponent($('search').value));
 if(revision!==searchRevision)return;
 $('tasks').replaceChildren();
 for(const item of items){
  const button=el('button',undefined,'task');button.type='button';button.dataset.id=item.id;button.setAttribute('aria-current',String(task?.id===item.id));
  button.append(el('strong',item.jira_id),el('span',item.title));
  button.onclick=()=>action(()=>selectTask(item.id));$('tasks').append(button);
 }
 if(!items.length)$('tasks').append(el('p','Задач не найдено.','muted'));
}
async function flushCases(){
 for(const [id,entry] of dirtyCases){
  const payload=entry.read();
  const saved=await api(entry.path,'PATCH',payload);
  Object.assign(entry.record,saved);
  if(JSON.stringify(entry.read())===JSON.stringify(payload)){dirtyCases.delete(id);entry.state.textContent='Сохранено · '+date(saved.updated_at);}else{await flushCases();}
 }
 renderCounts();
}
async function canLeave(){
 await flushCases();
 if(!task)return true;
 const gen=await generatorReady;
 const changed=JSON.stringify(gen.snapshot())!==settingsBaseline;
 const resultChanged=JSON.stringify(gen.cases())!==resultBaseline;
 return !(changed||resultChanged)||confirm('Есть несохранённые настройки или новый набор. Переключиться без их сохранения?');
}
async function selectTask(id,skipCheck=false){
 if(!skipCheck&&!await canLeave())return;
 const next=await api(`/api/tasks/${id}`);
 const gen=await generatorReady;await gen.ready;
 task=next;currentSet=null;dirtyCases.clear();gen.restore(task.settings);
 settingsBaseline=JSON.stringify(gen.snapshot());resultBaseline=JSON.stringify(gen.cases());
 $('empty').hidden=true;$('active').hidden=false;
 $('editTask').elements.jira_id.value=task.jira_id;$('editTask').elements.title.value=task.title;
 $('dates').textContent=`Создана ${date(task.created_at)} · Изменена ${date(task.updated_at)}`;
 $('setName').value='';$('settingsState').textContent='Настройки загружены';
 await loadSets();await listTasks();notice(`Открыта ${task.jira_id}`);
}
async function loadSets(preferred){
 const sets=await api(taskPath()+'/sets');$('sets').replaceChildren();
 sets.forEach(set=>{const option=el('option',`${set.name} · ${date(set.created_at)} · ${set.case_count} кейсов`);option.value=set.id;$('sets').append(option);});
 if(preferred)$('sets').value=preferred;
 if(sets.length)await loadSet(Number($('sets').value));else{currentSet=null;renderCases();}
}
async function loadSet(id){currentSet=await api(taskPath()+'/sets/'+id);$('statusFilter').value='';renderCases();}
function renderCounts(){
 $('counts').replaceChildren();
 for(const status of statuses){const count=currentSet?.cases.filter(c=>c.status===status).length||0;$('counts').append(el('span',`${status}: ${count}`));}
}
function inputField(label,value,kind='textarea'){
 const wrapper=el('label',label);const input=el(kind);input.value=value??'';wrapper.append(input);return [wrapper,input];
}
function renderCases(){
 $('cases').replaceChildren();renderCounts();
 $('sendSet').disabled=!currentSet;$('restoreSettings').disabled=!currentSet;
 $('setInfo').textContent=currentSet?`Регион: ${currentSet.region} · ${currentSet.operation} · ${date(currentSet.created_at)} · Изменения кейсов сохраняются при выходе из поля.`:'Сохранённых наборов пока нет.';
 if(!currentSet)return;
 for(const record of currentSet.cases){
  const card=el('article',undefined,'case');card.dataset.status=record.status;card.dataset.caseId=record.id;
  const heading=el('h3',record.title);const body=el('pre',record.text);
  const [statusLabel,status]=inputField('Статус',record.status,'select');
  statuses.forEach(value=>status.append(el('option',value)));status.value=record.status;
  const [qaLabel,qa]=inputField('Комментарии QA',record.qa_comment);qa.maxLength=20000;
  const [bugsLabel,bugs]=inputField('Ссылки на Jira-баги · одна ссылка на строку',record.bug_links.join('\n'));bugs.placeholder='https://company.atlassian.net/browse/QA-123';
  const details=el('details');details.append(el('summary','Редактировать кейс и текст для Slack'));
  const [titleLabel,title]=inputField('Название',record.title,'input');title.maxLength=4000;
  const [textLabel,text]=inputField('Шаги и ожидаемый результат',record.text);text.className='body';text.maxLength=100000;
  const [requestLabel,request]=inputField('Обращение в Slack',record.request_text);request.maxLength=2000;
  const [commentLabel,comment]=inputField('Дополнительные инструкции для Slack',record.comment);comment.maxLength=20000;
  details.append(titleLabel,textLabel,requestLabel,commentLabel);
  const state=el('span','Сохранено','saved');const save=el('button','Сохранить изменения','secondary');save.type='button';
  const grid=el('div',undefined,'result-grid');const left=el('div');left.append(statusLabel,bugsLabel);grid.append(left,qaLabel);
  const history=el('div',undefined,'slack-history');renderSlackHistory(record,history);
  const send=el('button','Отправить кейс в Slack','secondary send-saved-case');send.type='button';send.onclick=()=>startSending([record]);
  card.append(heading,send,history,body,grid,details,save,state);$('cases').append(card);
  const read=()=>({title:title.value,text:text.value,request_text:record.request_text===null&&!request.value?null:request.value,comment:comment.value,status:status.value,qa_comment:qa.value,bug_links:bugs.value.split('\n').map(x=>x.trim()).filter(Boolean)});
  const entry={read,record,state,path:`${setPath()}/cases/${record.id}`};
  for(const input of [status,qa,bugs,title,text,request,comment]){
   input.addEventListener('input',()=>{dirtyCases.set(record.id,entry);state.textContent='Не сохранено';});
   input.addEventListener('change',()=>{dirtyCases.set(record.id,entry);action(async()=>{await flushCases();heading.textContent=record.title;body.textContent=record.text;card.dataset.status=record.status;notice('Изменения сохранены');});});
  }
  save.onclick=()=>action(async()=>{dirtyCases.set(record.id,entry);await flushCases();heading.textContent=record.title;body.textContent=record.text;card.dataset.status=record.status;notice('Изменения сохранены');});
 }
 applyFilter();
}
function applyFilter(){for(const card of $('cases').children)card.hidden=!!$('statusFilter').value&&card.dataset.status!==$('statusFilter').value;}
$('statusFilter').onchange=applyFilter;
$('create').onsubmit=event=>{event.preventDefault();action(async()=>{if(!await canLeave())return;const created=await api('/api/tasks','POST',formValue(event.target));event.target.reset();$('search').value='';await selectTask(created.id,true);});};
$('editTask').onsubmit=event=>{event.preventDefault();action(async()=>{task=await api(taskPath(),'PUT',formValue(event.target));await listTasks();notice('Задача сохранена');});};
$('deleteTask').onclick=()=>action(async()=>{
 if(!confirm(`Удалить ${task.jira_id} и все её наборы без возможности восстановления?`))return;
 await api(taskPath(),'DELETE');task=null;currentSet=null;dirtyCases.clear();$('active').hidden=true;$('empty').hidden=false;
 (await generatorReady).restore();await listTasks();notice('Задача удалена');
});
$('search').oninput=()=>listTasks().catch(e=>notice(e.message,true));
$('sets').onchange=()=>{const id=Number($('sets').value);action(async()=>{try{await flushCases();await loadSet(id);}catch(e){$('sets').value=currentSet.id;throw e;}});};
$('saveSettings').onclick=()=>action(async()=>{
 const snapshot=(await generatorReady).snapshot();await api(taskPath()+'/settings','PUT',snapshot);settingsBaseline=JSON.stringify(snapshot);$('settingsState').textContent='Сохранено';notice('Настройки задачи сохранены');
});
$('saveSet').onclick=()=>action(async()=>{
 await flushCases();const gen=await generatorReady;const result=gen.result();if(!result.cases.length)throw new Error('Сначала сгенерируйте кейсы.');
 const snapshot=gen.snapshot();const saved=await api(taskPath()+'/sets','POST',{...result,settings:snapshot,name:$('setName').value.trim()||'Набор · '+new Date().toLocaleString('ru-RU')});
 settingsBaseline=JSON.stringify(snapshot);resultBaseline=JSON.stringify(result.cases);await loadSets(saved.id);notice('Новый набор и настройки сохранены. Предыдущие наборы остались в истории.');
});
$('restoreSettings').onclick=()=>action(async()=>{
 if(!currentSet||!await canLeave())return;
 (await generatorReady).restore(currentSet.settings);$('generatorPanel').open=true;
 notice('Настройки набора загружены в генератор. Сохраните их для задачи или создайте новый набор.');
});
let sending=false;
function startSending(records){
 if(sending)return;
 sending=true;
 const selectedSetId=currentSet.id;
 const selectedTaskId=task.id;
 document.querySelectorAll('#sendSet,.send-saved-case').forEach(button=>button.disabled=true);
 action(async()=>{
  try{
   if(task?.id!==selectedTaskId||currentSet?.id!==selectedSetId)throw new Error('Задача изменилась. Выберите кейсы заново.');
   await flushCases();notice('Отправка в Slack…');
   const result=await api('/slack/send-cases','POST',{
    region:currentSet.region,operation:currentSet.operation,mention_users:currentSet.mention_users,
    cases:records.map(({id,title,text,comment,request_text})=>({case_ids:[id],title,text,comment,request_text}))
   });
   const pending=result.deliveries.filter(send=>!send.permalink).length;
   notice(`В Slack отправлено кейсов: ${result.sent}`+(pending?` · Ссылка пока недоступна для ${pending}. Используйте «Получить ссылку»; сообщения уже отправлены.`:''));
  }catch(error){
   notice(error.message+' Отправка не повторяется автоматически. Перед новой отправкой проверьте историю и Slack.',true);
  }finally{
   // Reload history even if a later message in the batch failed. Preserve edits.
   try{if(task?.id===selectedTaskId&&currentSet?.id===selectedSetId)await refreshSlackHistory();}
   finally{sending=false;document.querySelectorAll('#sendSet,.send-saved-case').forEach(button=>button.disabled=false);}
  }
 });
}
$('sendSet').onclick=()=>startSending([...currentSet.cases]);
function renderSlackHistory(record,host){
 host.replaceChildren(el('strong','Отправки в Slack'));
 const sends=record.slack_sends||[];
 if(!sends.length){host.append(el('p','Сохранённых отправок пока нет.','muted'));return;}
 const list=el('ul');host.append(list);
 for(const send of sends){
  const item=el('li');item.append(el('span',date(send.sent_at)+' · '));
  if(send.permalink){
   const link=el('a','Открыть в Slack');link.href=send.permalink;link.target='_blank';link.rel='noopener noreferrer';item.append(link);
  }else{
   item.append(el('span','Отправлено, ссылка пока недоступна. '));
   const retry=el('button','Получить ссылку','secondary');retry.type='button';
   retry.onclick=()=>{
    retry.disabled=true;
    const path=`${setPath()}/cases/${record.id}/slack-sends/${send.id}/permalink`;
    action(async()=>{
     try{const updated=await api(path,'POST');await refreshSlackHistory();notice(updated.permalink?'Ссылка сохранена.': 'Сообщение уже отправлено. Ссылка пока недоступна; можно повторить только получение ссылки.',!updated.permalink);}
     finally{retry.disabled=false;}
    });
   };item.append(retry);
  }
  list.append(item);
 }
}
async function refreshSlackHistory(){
 const updated=await api(setPath());
 for(const record of currentSet.cases){
  record.slack_sends=updated.cases.find(c=>c.id===record.id)?.slack_sends||[];
  const host=document.querySelector(`[data-case-id="${record.id}"] .slack-history`);
  if(host)renderSlackHistory(record,host);
 }
}
async function slackStatus(){const value=await api('/api/slack-status');$('slackStatus').textContent=value.connected?'Slack подключён':'Slack не подключён';}
window.addEventListener('focus',()=>slackStatus().catch(()=>{}));
window.addEventListener('beforeunload',event=>{
 const gen=frame.contentWindow.qaGenerator;
 if(pendingActions||dirtyCases.size||(task&&gen&&(JSON.stringify(gen.snapshot())!==settingsBaseline||JSON.stringify(gen.cases())!==resultBaseline))){event.preventDefault();event.returnValue='';}
});
Promise.all([listTasks(),slackStatus()]).then(()=>notice('Выберите задачу или создайте новую.')).catch(e=>notice(e.message,true));
