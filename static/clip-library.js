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
  if(op==='archive'&&!confirm('Переместить выбранные записи в архив?'))e.preventDefault();
 });
 window.addEventListener('clip-library-refresh',update);
 update();
 const dialog=document.getElementById('clip-dialog'),player=document.getElementById('clip-player');
 let generation=0;
 async function openClip(id){
  const token=++generation;
  document.getElementById('clip-dialog-title').textContent='Ролик #'+id;
  document.getElementById('clip-dialog-meta').textContent='';
  document.getElementById('clip-dialog-quality').textContent='';
  document.getElementById('clip-dialog-message').textContent='Загрузка…';
  for(const key of ['clip-download','clip-cover-download','clip-source-link'])document.getElementById(key).hidden=true;
  player.src='/clips/'+id+'/video';
  if(!dialog.open)dialog.showModal();
  try{
   const response=await fetch('/api/clips/'+id,{cache:'no-store'});
   if(!response.ok)throw Error('Файл недоступен');
   const c=await response.json();if(token!==generation)return;
   document.getElementById('clip-dialog-title').textContent=c.title||'Ролик #'+id;
   document.getElementById('clip-dialog-meta').textContent=[c.source,Math.round(c.duration)+' с',c.campaign||'Без рекламы',c.run_id?'Партия #'+c.run_id:''].filter(Boolean).join(' · ');
   const q=c.quality||{};
   document.getElementById('clip-dialog-quality').textContent=[q.width&&q.height?q.width+' × '+q.height:'',q.fps?q.fps+' FPS':'',(c.bytes/1048576).toFixed(1)+' МиБ'].filter(Boolean).join(' · ');
   const download=document.getElementById('clip-download');download.href=player.src;download.download='clip_'+id+'.mp4';download.hidden=false;
   const cover=document.getElementById('clip-cover-download');cover.href='/clips/'+id+'/cover';cover.download='clip_'+id+'.jpg';cover.hidden=!c.has_cover;
   const source=document.getElementById('clip-source-link');source.hidden=!c.source_url;if(c.source_url)source.href=c.source_url;
   document.getElementById('clip-dialog-message').textContent='';
  }catch(e){if(token===generation)document.getElementById('clip-dialog-message').textContent=e.message;}
 }
 document.addEventListener('click',e=>{const b=e.target.closest('[data-open-clip]');if(b){e.preventDefault();openClip(b.dataset.openClip);}});
 document.getElementById('clip-dialog-close').addEventListener('click',()=>dialog.close());
 dialog.addEventListener('close',()=>{generation++;player.pause();player.removeAttribute('src');player.load();});
 window.addEventListener('clip-library-refresh',update);
})();
