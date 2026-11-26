(() => {
 const $=id=>document.getElementById(id);
 const list=$('queue-list');if(!list)return;
 let filter='active',items=[],busy=false,posting=false,lastKey='';
 const groups={active:['pending','running'],attention:['failed','ad_review'],filtered:['duplicate','ad_rejected'],cancelled:['cancelled']};
 const labels={pending:'Ожидает',running:'Обрабатывается',failed:'Ошибка',ad_review:'Нужна проверка',duplicate:'Дубликат',ad_rejected:'Реклама',cancelled:'Отменено'};
 function node(tag,text,cls){const n=document.createElement(tag);if(text)n.textContent=text;if(cls)n.className=cls;return n;}
 async function action(id,op){
  if(posting)return;
  if(op==='cancel'&&!confirm('Отменить задачу? Исходник сохранится.'))return;
  posting=true;render();
  try{
   const data=new FormData();data.append('csrf',$('queue-csrf').value);
   const r=await fetch('/queue/'+id+'/'+op,{method:'POST',body:data,redirect:'follow'});
   if(!r.ok)throw Error(r.status===409?'Сначала приостановите производство.':'Операция не выполнена (HTTP '+r.status+').');
   $('queue-message').textContent=op==='retry'?'Повторный монтаж запущен.':'Изменения сохранены.';
   lastKey='';
  }catch(e){$('queue-message').textContent=e.message;}
  finally{posting=false;await poll();}
 }
 function render(){
  const q=$('queue-search').value.trim().toLowerCase();
  const visible=items.filter(c=>groups[filter].includes(c.status)&&(!q||String(c.id)===q.replace(/^#/,'')||(c.title||'').toLowerCase().includes(q)));
  const key=JSON.stringify([visible,busy,posting]);
  if(key===lastKey)return;lastKey=key;
  const opened=new Set([...list.querySelectorAll('details[open]')].map(d=>d.dataset.id));
  list.replaceChildren();
  $('queue-count').textContent='Показано: '+visible.length;
  for(const c of visible){
   const row=node('article','','queue-row'), info=node('div','','queue-info');
   info.append(node('h4',c.title||'Ролик #'+c.id),node('p','#'+c.id+' · '+c.source+' · '+labels[c.status]+(c.run_id?' · Партия #'+c.run_id:''),'muted'));
   if(c.issue.title){info.append(node('strong',c.issue.title),node('p',c.issue.help));}
   if(c.error||c.ad_result){
    const details=node('details');details.dataset.id=String(c.id);details.open=opened.has(String(c.id));details.append(node('summary','Технические подробности'),node('pre',c.error||c.ad_result));info.append(details);
   }
   const actions=node('div','','queue-actions');
   const button=(title,op)=>{const b=node('button',title,'secondary');b.type='button';b.disabled=busy||posting;b.addEventListener('click',()=>action(c.id,op));actions.append(b);};
   if(c.status==='pending'){button('Повысить приоритет','priority');button('Отменить','cancel');}
   if(c.status==='cancelled')button('Восстановить','restore');
   if(c.can_retry)button('Повторить сейчас','retry');
   else if(['failed','ad_review'].includes(c.status))actions.append(node('small','Нет сохранённых настроек старой задачи','muted'));
   row.append(info,actions);list.append(row);
  }
  if(!visible.length)list.append(node('p','В этом разделе нет задач.','muted queue-empty'));
 }
 document.querySelectorAll('[data-queue-filter]').forEach(b=>b.addEventListener('click',()=>{
  filter=b.dataset.queueFilter;document.querySelectorAll('[data-queue-filter]').forEach(x=>x.classList.toggle('active',x===b));render();
 }));
 $('queue-search').addEventListener('input',render);
 async function poll(){
  try{
   const [r,j]=await Promise.all([fetch('/api/queue',{cache:'no-store'}),fetch('/api/job-status',{cache:'no-store'})]);
   if(!r.ok||!j.ok)throw Error('Нет связи');
   const d=await r.json();busy=(await j.json()).running;items=d.items;
   document.querySelectorAll('[data-queue-filter]').forEach(b=>{b.querySelector('span').textContent=groups[b.dataset.queueFilter].reduce((n,k)=>n+(d.counts[k]||0),0);});
   render();
  }catch(e){$('queue-message').textContent='Не удалось обновить очередь.';}
 }
 async function loop(){await poll();setTimeout(loop,2500);}
 loop();
})();
