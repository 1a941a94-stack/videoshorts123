(() => {
 const views={
  overview:{title:'Производство',ids:['production-live','production-runs','production-controls']},
  queue:{title:'Очередь производства',ids:['queue']},
  configurations:{title:'Конфигурации',ids:['run-configurations']},
  production:{title:'Расширенное производство',ids:['production-live','production-controls','factory']},
  library:{title:'Источники',ids:['sources','telegram','manual-import','local-library','videos']},
  results:{title:'Готовые ролики',ids:['clips']},
  design:{title:'Шаблоны',ids:['saved-templates','short-template']},
  media:{title:'Медиатека',ids:['media-library']},
  profiles:{title:'Профили монтажа',ids:['production-profiles']},
  ads:{title:'Рекламные кампании',ids:['campaigns']},
  storage:{title:'Хранилище',ids:['storage']},
  system:{title:'Диагностика и настройки',ids:['diagnostics','performance','settings','ad-references']}
 };
 const links=[...document.querySelectorAll('nav [data-view]')];
 const sections=[...document.querySelectorAll('main > section')];
 const title=document.getElementById('workspace-title');
 if(!title||!sections.length)return;
 const lookup={overview:'overview'};
 for(const [name,view] of Object.entries(views))for(const id of view.ids)if(!lookup[id])lookup[id]=name;
 lookup['production-controls']='production';
 function show(){
  const hash=location.hash.slice(1);
  const key=lookup[hash]||'overview';
  const trash=key==='results'&&new URLSearchParams(location.search).get('clip_status')==='archived';
  const view=views[key];
  for(const section of sections)section.hidden=!view.ids.includes(section.id);
  title.textContent=trash?'Корзина':view.title;
  const refresh=document.getElementById('workspace-refresh');if(refresh)refresh.href=location.pathname+location.search+location.hash;
  requestAnimationFrame(()=>window.dispatchEvent(new Event('workspace-change')));
  for(const link of links){
   const active=trash?link.dataset.view==='trash':link.dataset.view===key;
   link.classList.toggle('active',active);
   if(active)link.setAttribute('aria-current','page');
   else link.removeAttribute('aria-current');
  }
  const metrics=document.getElementById('workspace-metrics');
  if(metrics)metrics.hidden=!['production'].includes(key);
  window.scrollTo(0,0);
 }
 window.addEventListener('hashchange',show);
 show();
})();
