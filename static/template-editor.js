(() => {
const f=document.getElementById('template-form'), p=document.getElementById('template-preview'), m=document.getElementById('preview-mask');
if(!f||!p||!m)return;
const v=k=>f.elements[k].value;
function draw(){
 const size=Number(v('size')),x=Number(v('x')),y=Number(v('y')),b=Number(v('border'));
 p.style.backgroundColor=v('color');
 const bg=v('background'), video=document.getElementById('preview-background-video');
 const motion=/\.(mp4|webm|mov)$/i.test(bg);
 const url=bg?'/short-backgrounds/'+encodeURIComponent(bg):'';
 p.style.backgroundImage=bg&&!motion?'url("'+url+'")':'none';
 if(video){
   video.hidden=!motion;
   if(motion){if(video.getAttribute('src')!==url){video.src=url;video.play().catch(()=>{});}}
   else if(video.hasAttribute('src')){video.pause();video.removeAttribute('src');video.load();}
 }
 m.style.width=(size+2*b)/1080*100+'%';
 m.style.left=(50+x/1080*100)+'%';
 m.style.top=(50+y/1920*100)+'%';
 m.style.borderRadius=v('layout')==='circle'?'50%':'0';
 m.style.border=b/1080*p.clientWidth+'px solid '+v('border_color');
 const source=document.getElementById('studio-source');if(source)source.style.objectFit=v('fit');
}
f.addEventListener('input',draw);
window.addEventListener('resize',draw);
window.addEventListener('workspace-change',draw);
document.querySelectorAll('.edit-profile').forEach(btn=>btn.addEventListener('click',()=>{
 const data=JSON.parse(btn.dataset.spec);
 f.elements.name.value=btn.dataset.name;
 for(const [k,val] of Object.entries(data))if(f.elements[k])f.elements[k].value=typeof val==='boolean'?Number(val):val;
 for(const [k,val] of Object.entries(data.caption_style||{}))if(f.elements['sub_'+k])f.elements['sub_'+k].value=typeof val==='boolean'?Number(val):val;
 draw(); f.scrollIntoView({behavior:'smooth',block:'center'});
}));
draw();
const btn=document.getElementById('render-preview'), player=document.getElementById('real-preview'), status=document.getElementById('preview-status');
let objectUrl='';
if(btn&&player&&status)btn.addEventListener('click',async()=>{
 btn.disabled=true;
 status.textContent='FFmpeg: создание предпросмотра…';
 try{
  const response=await fetch('/short-preview',{method:'POST',body:new FormData(f)});
  if(!response.ok)throw new Error('Предпросмотр не создан (HTTP '+response.status+'). Проверьте настройки и файл.');
  const blob=await response.blob();
  if(objectUrl)URL.revokeObjectURL(objectUrl);
  objectUrl=URL.createObjectURL(blob);
  player.src=objectUrl;
  player.hidden=false;
  status.textContent='Готово: до 5 секунд.'+(response.headers.get('X-Banner-Overlap')==='1'?' Внимание: реклама может перекрывать видео.':'');
 }catch(e){status.textContent=e.message;}
 finally{btn.disabled=false;}
});
window.addEventListener('pagehide',()=>{if(objectUrl)URL.revokeObjectURL(objectUrl);});
})();
