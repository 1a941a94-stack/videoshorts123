(() => {
const $=id=>document.getElementById(id);
if(!$('production-runs'))return;
const form=$('config-form'), launch=$('run-launch'), select=$('launch-config');
let configurations={}, recentKey='';
function description(){
 if(!select)return;
 const item=configurations[select.value];
 if(item)$('launch-description').textContent=[item.mode==='short'?'Готовые мемы':'Подкасты',item.template||'Стандартный шаблон',item.campaign||'Без рекламы',item.auto_search?'Автопоиск включён':'Только очередь'].join(' · ');
}
if(select)select.addEventListener('change',()=>{$('launch-goal').value=select.selectedOptions[0].dataset.goal;description();});
document.querySelectorAll('.config-edit').forEach(b=>b.addEventListener('click',()=>{
 const item=JSON.parse(b.dataset.item);
 form.elements.name.value=b.dataset.name;
 for(const [key,value] of Object.entries(item)){
  const field=form.elements[key];if(!field)continue;
  if(field.type==='checkbox')field.checked=Boolean(value);else field.value=value;
 }
 $('config-heading').textContent='Редактирование конфигурации';form.scrollIntoView({block:'start'});
}));
$('config-reset').addEventListener('click',()=>{form.reset();$('config-heading').textContent='Новая конфигурация';});
document.querySelectorAll('.config-delete').forEach(f=>f.addEventListener('submit',e=>{if(!confirm('Удалить конфигурацию? Готовые видео и партии сохранятся.'))e.preventDefault();}));
const statuses={queued:'Ожидает запуска',running:'В работе',paused:'Пауза',completed:'Цель достигнута',exhausted:'Нет подходящих кандидатов',failed:'Ошибка партии',stopped:'Остановлена'};
function recent(items){
 const key=JSON.stringify(items);if(key===recentKey)return;recentKey=key;
 const grid=$('home-recent');grid.replaceChildren();
 if(!items.length){grid.textContent='Здесь появятся видео сразу после монтажа.';return;}
 for(const c of items){
  const card=document.createElement('article');card.className='home-clip';
  const view=document.createElement('a');view.href='/clips/'+c.id+'/video';view.target='_blank';view.rel='noopener';
  if(c.cover){const img=document.createElement('img');img.src='/clips/'+c.id+'/cover';img.alt='';img.loading='lazy';view.append(img);}
  else{const span=document.createElement('span');span.className='clip-placeholder';span.textContent='▶';view.append(span);}
  const title=document.createElement('strong');title.textContent=c.title||'Ролик #'+c.id;
  const actions=document.createElement('div');
  for(const [label,download] of [['Смотреть',false],['Скачать',true]]){
   const a=document.createElement('a');a.href=view.href;a.textContent=label;
   if(download)a.download='clip_'+c.id+'.mp4';else{a.target='_blank';a.rel='noopener';}
   actions.append(a);
  }
  card.append(view,title,actions);grid.append(card);
 }
}
async function poll(){
 try{
  const response=await fetch('/api/production',{cache:'no-store'});if(!response.ok)throw Error(response.status);
  const d=await response.json();configurations=d.configurations.items;description();
  $('home-today').textContent=d.today;$('home-pending').textContent=d.stats.pending||0;
  $('home-attention').textContent=(d.stats.failed||0)+(d.stats.ad_review||0);
  const b=d.runs.find(r=>r.id===d.active_id)||d.runs[0];
  if(b){
   const done=b.counts.done||0;
   $('batch-status').textContent=statuses[b.status]||b.status;
   $('batch-name').textContent=b.name+' · Партия #'+b.id;
   $('batch-done').textContent=done;$('batch-goal').textContent='/ '+b.goal;
   $('batch-fill').style.width=Math.min(100,100*done/b.goal)+'%';
   $('batch-detail').textContent='Отсеяно: '+((b.counts.duplicate||0)+(b.counts.ad_rejected||0))+' · Ошибки: '+(b.counts.failed||0)+' · На проверке: '+(b.counts.ad_review||0);
   $('batch-pause').hidden=d.active_id!==b.id;
   $('batch-resume').hidden=Boolean(d.active_id)||!['paused','queued','running'].includes(b.status);
   $('batch-pause').action='/production/'+b.id+'/pause';$('batch-resume').action='/production/'+b.id+'/resume';
  }
  if(launch)launch.querySelector('button').disabled=Boolean(d.active_id);
  recent(d.recent);
 }catch(e){$('batch-status').textContent='Не удалось обновить данные';}
 finally{setTimeout(poll,2000);}
}
poll();
})();
