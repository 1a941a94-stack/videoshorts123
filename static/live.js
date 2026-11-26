(() => {
const $=id=>document.getElementById(id);
const actions={scan:'Поиск видео',work:'Монтаж роликов',retry:'Возврат задач в очередь',send:'Публикация'};
const stages={search:'Поиск источника',inspect:'Проверка видео и пиков',download:'Скачивание фрагмента',framing:'Анализ лиц и кадрирование',captions:'Распознавание речи',render:'Рендеринг видео',save:'Сохранение результата',error:'Ошибка задачи',retry:'Задач возвращено в очередь'};
let priorRunning=false, initial=true;
function clock(s){return [Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(x=>String(x).padStart(2,'0')).join(':')}
async function poll(){
 try{
 const res=await fetch('/api/job-status',{cache:'no-store',signal:AbortSignal.timeout(8000)});
 if(!res.ok)throw Error(res.status);
 const d=await res.json();
 $('live-connection').textContent='● Связь с сервером';
 const mode=d.running?'running':d.result===null?'idle':d.result===0?'finished':'failed';
 $('live-job').dataset.state=mode;
 $('live-title').textContent=d.running?(actions[d.action]||'Обработка'):mode==='idle'?'Готов к работе':mode==='finished'?'Процесс завершён':'Процесс завершился с ошибкой';
 $('live-stage').textContent=[stages[d.stage],d.detail].filter(Boolean).join(' · ')||'—';
 $('live-time').textContent=clock(Math.max(0,d.elapsed||0));
 const known=Number.isInteger(d.total)&&d.total>0&&Number.isInteger(d.done);
 const pct=known?Math.min(100,Math.round(d.done/d.total*100)):0;
 $('live-track').classList.toggle('indeterminate',d.running&&!known);
 $('live-fill').style.width=known?pct+'%':d.running?'35%':'0%';
 if(known){$('live-track').setAttribute('aria-valuenow',pct);$('live-track').setAttribute('aria-valuemin',0);$('live-track').setAttribute('aria-valuemax',100)}else $('live-track').removeAttribute('aria-valuenow');
 $('live-count').textContent=known?d.done+' / '+d.total+' '+(d.action==='scan'?'источников':'задач')+' · '+pct+'%':'Прогресс пока неизвестен';
 $('live-activity').textContent=d.running?(d.log_age===null?'Ожидание первого сообщения':d.log_age>45?'Нет новых сообщений '+d.log_age+' с — процесс ещё запущен':'Последняя активность '+d.log_age+' с назад'):d.result===null?'Ожидание команды':'Код завершения: '+d.result;
 $('live-current').textContent=d.active.map(c=>'#'+c.id+' · '+(c.title||'')).join(' | ');
 const log=$('live-log'), follow=log.scrollHeight-log.scrollTop-log.clientHeight<40;
 if(log.textContent!==d.log){log.textContent=d.log;if(follow)log.scrollTop=log.scrollHeight}
 const keys=['videos','pending','running','done','failed'];
 document.querySelectorAll('.metrics strong').forEach((el,i)=>el.textContent=d.stats[keys[i]]||0);
 document.querySelectorAll('.actions button').forEach(b=>b.disabled=d.running);
 if(!initial&&priorRunning&&!d.running){
  // Refresh results only, keeping form inputs and live log intact.
  const html=await fetch('/',{cache:'no-store'}).then(r=>r.text());
  const doc=new DOMParser().parseFromString(html,'text/html');
  for(const id of ['videos','clips']){const old=$(id).querySelector('.table'),fresh=doc.getElementById(id).querySelector('.table');if(old&&fresh)old.replaceWith(fresh)}
 }
 priorRunning=d.running;initial=false;
 }catch(e){$('live-connection').textContent='Нет связи с сервером';$('live-activity').textContent='Повторяем подключение…';$('live-job').dataset.state='offline'}
 finally{setTimeout(poll,1500)}
}
poll();
})();