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
})();
