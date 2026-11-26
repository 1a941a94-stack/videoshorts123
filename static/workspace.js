(() => {
 const views={
  overview:{title:'Производство',ids:['production-runs','production-controls']},
  configurations:{title:'Конфигурации',ids:['run-configurations']},
  production:{title:'Расширенное производство',ids:['production-controls','factory']},
  library:{title:'Библиотека видео',ids:['local-library','telegram','sources','videos']},
  results:{title:'Готовые ролики',ids:['clips']},
  design:{title:'Шаблоны и фоны',ids:['short-template']},
  profiles:{title:'Профили монтажа',ids:['production-profiles']},
  ads:{title:'Рекламные кампании',ids:['campaigns','ad-references']},
  system:{title:'Диагностика и настройки',ids:['performance','settings']}
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
  const view=views[key];
  for(const section of sections)section.hidden=!view.ids.includes(section.id);
  title.textContent=view.title;
  requestAnimationFrame(()=>window.dispatchEvent(new Event('workspace-change')));
  for(const link of links){
   const active=link.dataset.view===key;
   link.classList.toggle('active',active);
   if(active)link.setAttribute('aria-current','page');
   else link.removeAttribute('aria-current');
  }
  const metrics=document.getElementById('workspace-metrics');
  if(metrics)metrics.hidden=!['production','results'].includes(key);
  window.scrollTo(0,0);
 }
 window.addEventListener('hashchange',show);
 show();
})();
