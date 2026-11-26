(() => {
 const form=document.getElementById('clip-bulk');
 if(!form)return;
 const all=document.getElementById('clip-select-all'), count=document.getElementById('clip-selection-count');
 const boxes=()=>[...form.querySelectorAll('input[name="ids"]:not(:disabled)')];
 function update(){
  const list=boxes(), n=list.filter(b=>b.checked).length;
  count.textContent=n+' выбрано';
  all.checked=list.length>0&&n===list.length;
  all.indeterminate=n>0&&n<list.length;
  form.querySelectorAll('button[name="operation"]').forEach(b=>b.disabled=n===0);
 }
 all.addEventListener('change',()=>{boxes().forEach(b=>b.checked=all.checked);update();});
 form.addEventListener('change',update);
 form.addEventListener('submit',e=>{
  const op=e.submitter?.value;
  if(!boxes().some(b=>b.checked)){e.preventDefault();return;}
  if(op==='remontage'&&!confirm('Вернуть выбранные ролики в очередь? Старые файлы сохранятся.'))e.preventDefault();
  if(op==='purge'&&!confirm('Окончательно удалить выбранные MP4 и обложки? Восстановить их будет невозможно.'))e.preventDefault();
  if(op==='archive'&&!confirm('Переместить выбранные записи в архив?'))e.preventDefault();
 });
 window.addEventListener('clip-library-refresh',update);
 update();
 const dialog=document.getElementById('clip-dialog'),player=document.getElementById('clip-player');
 let generation=0, currentId=null;
 const edit=document.getElementById('clip-edit-form'),toggle=document.getElementById('clip-edit-toggle'),msg=document.getElementById('clip-dialog-message');
 toggle.addEventListener('click',async()=>{
  if(!edit.hidden){edit.hidden=true;return;}
  const id=currentId,token=generation;
  try{
   const res=await fetch('/api/clips/'+id+'/edit');if(!res.ok)throw Error('Настройки недоступны');
   const data=await res.json();if(token!==generation)return;
   for(const [name,items,empty] of [['background',data.backgrounds,'Цвет фона'],['campaign',data.campaigns,'Без рекламы']]){
    const field=edit.elements[name];field.replaceChildren(new Option(empty,''));
    for(const item of items)field.add(new Option(item,item));
   }
   for(const [key,value] of Object.entries(data.template))if(edit.elements[key])edit.elements[key].value=value;
   edit.elements.campaign.value=data.campaign;
   if(edit.elements.campaign.selectedIndex<0)edit.elements.campaign.selectedIndex=0;
   edit.elements.captions.checked=data.captions;
   document.getElementById('clip-edit-note').textContent=data.known?'Настройки предыдущей задачи загружены.':'Исходные настройки старого ролика не сохранены. Проверьте предложенные значения.';
   edit.hidden=false;
  }catch(e){msg.textContent=e.message;}
 });
 edit.addEventListener('submit',async e=>{
  e.preventDefault();const token=generation,id=currentId,button=edit.querySelector('button[type=submit]');
  button.disabled=true;
  try{
   const res=await fetch('/clips/'+id+'/edit',{method:'POST',body:new FormData(edit)});
   const data=await res.json();if(!res.ok)throw Error(data.error||'Не удалось запустить монтаж');
   if(token!==generation)return;
   edit.hidden=true;toggle.hidden=true;msg.textContent='Монтаж запущен. Партия #'+data.run_id+'. Предыдущая версия доступна.';
  }catch(e){if(token===generation)msg.textContent=e.message;}
  finally{button.disabled=false;}
 });
 async function openClip(id){
  const token=++generation;currentId=id;edit.hidden=true;toggle.hidden=true;
  document.getElementById('clip-dialog-title').textContent='Ролик #'+id;
  document.getElementById('clip-dialog-meta').textContent='';
  document.getElementById('clip-dialog-quality').textContent='';
  document.getElementById('clip-dialog-message').textContent='Загрузка…';
  for(const key of ['clip-download','clip-cover-download','clip-source-link'])document.getElementById(key).hidden=true;
  player.src='/clips/'+id+'/video';
  document.getElementById('clip-history').open=false;
  document.getElementById('clip-history-list').replaceChildren();
  if(!dialog.open)dialog.showModal();
  try{
   const response=await fetch('/api/clips/'+id,{cache:'no-store'});
   if(!response.ok)throw Error('Файл недоступен');
   const c=await response.json();if(token!==generation)return;
   document.getElementById('clip-dialog-title').textContent=c.title||'Ролик #'+id;
   document.getElementById('clip-dialog-meta').textContent=[c.source,Math.round(c.duration)+' с',c.campaign||'Без рекламы',c.run_id?'Партия #'+c.run_id:''].filter(Boolean).join(' · ');
   toggle.hidden=c.mode!=='short'||!['done','failed','ad_review','ad_rejected','duplicate'].includes(c.status);
   const q=c.quality||{};
   document.getElementById('clip-dialog-quality').textContent=[q.width&&q.height?q.width+' × '+q.height:'',q.fps?q.fps+' FPS':'',(c.bytes/1048576).toFixed(1)+' МиБ'].filter(Boolean).join(' · ');
   const download=document.getElementById('clip-download');download.href=player.src;download.download='clip_'+id+'.mp4';download.hidden=false;
   const cover=document.getElementById('clip-cover-download');cover.href='/clips/'+id+'/cover';cover.download='clip_'+id+'.jpg';cover.hidden=!c.has_cover;
   const source=document.getElementById('clip-source-link');source.hidden=!c.source_url;if(c.source_url)source.href=c.source_url;
   document.getElementById('clip-dialog-message').textContent='';
   fetch('/api/clips/'+id+'/versions',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{
    if(token!==generation)return;
    const list=document.getElementById('clip-history-list');list.replaceChildren();
    if(!data.versions.length){list.textContent='Нет предыдущих версий';return;}
    for(const v of data.versions){
     const row=document.createElement('p'),play=document.createElement('button'),download=document.createElement('a');
     const url='/clips/'+id+'/versions/'+v.id+'/video';
     play.type='button';play.className='secondary';play.textContent=new Date(v.created*1000).toLocaleString()+' · Смотреть';
     play.onclick=()=>{player.src=url;player.play().catch(()=>{});};
     download.href=url;download.download='clip_'+id+'_version_'+v.id+'.mp4';download.textContent=' Скачать';
     row.append(play,download);list.append(row);
    }
    const current=document.createElement('button');current.type='button';current.className='secondary';current.textContent='Текущая версия';current.onclick=()=>{player.src='/clips/'+id+'/video';};list.prepend(current);
   }).catch(()=>{if(token===generation)document.getElementById('clip-history-list').textContent='История недоступна';});
  }catch(e){if(token===generation)document.getElementById('clip-dialog-message').textContent=e.message;}
 }
 document.addEventListener('click',e=>{const b=e.target.closest('[data-open-clip]');if(b){e.preventDefault();openClip(b.dataset.openClip);}});
 document.getElementById('clip-dialog-close').addEventListener('click',()=>dialog.close());
 dialog.addEventListener('close',()=>{generation++;player.pause();player.removeAttribute('src');player.load();});
 window.addEventListener('clip-library-refresh',update);
})();
