(() => {
const $=id=>document.getElementById(id);
if(!$('storage'))return;
const fmt=n=>(n/1073741824).toFixed(2)+' ГиБ';
function line(parent,label,value,cls=''){
 const row=document.createElement('div');row.className='maintenance-row '+cls;
 const a=document.createElement('span'),b=document.createElement('span');a.textContent=label;b.textContent=value;row.append(a,b);parent.append(row);
}
async function storage(){
 try{const r=await fetch('/api/storage',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();$('storage-free').textContent='Свободно '+fmt(d.free)+' из '+fmt(d.total);const p=$('storage-breakdown');p.replaceChildren();
 for(const [key,label] of Object.entries({output:'Готовые файлы и версии',originals:'Локальные исходники',cache:'Кеш скачивания',trash:'Корзина',assets:'Материалы оформления'}))line(p,label,fmt(d[key]));
 }catch{$('storage-free').textContent='Не удалось получить данные хранилища.';}
}
async function diagnostics(){
 const p=$('diagnostics-list');p.textContent='Проверка…';
 try{const r=await fetch('/api/diagnostics',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();p.replaceChildren();for(const c of d.checks)line(p,c.name,(c.ok?'Готово · ':c.required?'Требуется внимание · ':'Необязательно · ')+c.detail,c.ok?'ready':'issue');}
 catch{p.textContent='Не удалось проверить систему.';}
}
$('storage-refresh').addEventListener('click',storage);$('diagnostics-refresh').addEventListener('click',diagnostics);
$('clear-cache-form').addEventListener('submit',e=>{if(!confirm('Очистить кеш скачивания? При необходимости исходники будут скачаны заново.'))e.preventDefault();});
let last='';
function show(){const hash=location.hash;if(hash===last)return;last=hash;if(hash==='#storage')storage();if(['#diagnostics','#performance','#settings','#ad-references'].includes(hash))diagnostics();}
window.addEventListener('workspace-change',show);show();
})();
