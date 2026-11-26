(() => {
 const form=document.getElementById('local-import-form'), out=document.getElementById('local-import-results');
 if(!form||!out)return;
 form.addEventListener('submit',async e=>{
  e.preventDefault();
  const files=Array.from(form.elements.videos.files), button=form.querySelector('button');
  if(!files.length||files.length>50){out.textContent='Выберите от 1 до 50 файлов.';return;}
  button.disabled=true;
  const lines=[];
  try {
   for(let i=0;i<files.length;i++){
    const file=files[i];
    out.textContent=lines.join('\n')+'\nИмпорт '+(i+1)+'/'+files.length+': '+file.name;
    try {
     if(file.size>64*1024*1024)throw new Error('Более 64 МиБ: используйте CLI');
     const data=new FormData();data.append('csrf',form.elements.csrf.value);data.append('videos',file);
     const response=await fetch('/local-import',{method:'POST',body:data});
     if(!response.ok)throw new Error('HTTP '+response.status);
     const result=(await response.json()).results[0];
     lines.push(file.name+': '+({ready:'Добавлено',duplicate:'Дубликат',error:'Ошибка'}[result.status]||result.status)+(result.detail?' — '+result.detail:''));
    } catch(err){lines.push(file.name+': '+err.message);}
   }
   out.textContent=lines.join('\n')+'\nИмпорт завершён. Обновите страницу для просмотра очереди.';
  } finally {button.disabled=false;}
 });
})();
