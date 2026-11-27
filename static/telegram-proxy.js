(() => {
 const f=document.getElementById('telegram-proxy-form'), status=document.getElementById('telegram-proxy-status'), check=document.getElementById('telegram-proxy-check');
 if(!f)return;
 async function load(){
  const r=await fetch('/api/telegram/proxy',{cache:'no-store'});
  if(!r.ok)throw Error('Настройки недоступны');
  const data=await r.json();
  for(const k of ['type','host','port','username'])f.elements[k].value=data[k]??'';
  f.elements.password.value='';
  f.elements.password.placeholder=data.has_password?'Пароль сохранён':'Необязательно';
  f.elements.clear_password.checked=false;
 }
 async function post(path){
  const r=await fetch(path,{method:'POST',body:new FormData(f)});
  const data=await r.json();
  if(!r.ok)throw Error(data.error||'Ошибка подключения');
  return data;
 }
 async function save(){await post('/telegram/proxy');await load();}
 f.addEventListener('submit',async e=>{e.preventDefault();try{await save();status.textContent='Настройки сохранены.';}catch(e){status.textContent=e.message;}});
 check.addEventListener('click',async()=>{check.disabled=true;status.textContent='Проверка подключения…';try{await save();const data=await post('/telegram/proxy/check');status.textContent=data.authorized?'Telegram подключён и авторизован.':'Соединение установлено. Выполните авторизацию через PowerShell.';}catch(e){status.textContent=e.message;}finally{check.disabled=false;}});
 load().catch(e=>status.textContent=e.message);
})();
