(() => {
const f=document.getElementById('template-form'),p=document.getElementById('template-preview'),m=document.getElementById('preview-mask'),v=document.getElementById('studio-source');
if(!f||!v)return;
const groups={video:['layout','size','x','y','border','border_color','fit','auto_crop','preview_source'],background:['color','background'],ad:['preview_campaign','ad_override','ad_width','ad_height','ad_x','ad_y','ad_opacity','ad_start','ad_end'],captions:['preview_captions','sub_size','sub_margin','sub_font','sub_color','sub_highlight','sub_outline_color','sub_outline','sub_shadow','sub_words','sub_alignment','sub_karaoke']};
function layer(key){document.querySelectorAll('[data-layer]').forEach(b=>b.classList.toggle('active',b.dataset.layer===key));for(const l of f.querySelectorAll('label')){const input=l.querySelector('[name]');l.hidden=!!input&&input.name!=='name'&&key!=='all'&&!groups[key].includes(input.name);}}
document.querySelectorAll('[data-layer]').forEach(b=>b.addEventListener('click',()=>layer(b.dataset.layer)));
layer('video');
let url='';
f.elements.preview_source.addEventListener('change',()=>{if(url)URL.revokeObjectURL(url);const file=f.elements.preview_source.files[0];if(file){url=URL.createObjectURL(file);v.src=url;v.play().catch(()=>{});}else{v.removeAttribute('src');v.load();}});
let drag=null;
m.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();layer('video');m.setPointerCapture(e.pointerId);drag={id:e.pointerId,x:e.clientX,y:e.clientY,s:Number(f.elements.size.value),ox:Number(f.elements.x.value),oy:Number(f.elements.y.value),resize:e.target.id==='studio-grip'};});
m.addEventListener('pointermove',e=>{if(!drag||e.pointerId!==drag.id)return;const scale=1080/p.clientWidth,b=Number(f.elements.border.value);const clamp=(x,a,z)=>Math.min(z,Math.max(a,x));if(drag.resize){const max=Math.min(1080-2*Math.abs(drag.ox),1920-2*Math.abs(drag.oy))-2*b;f.elements.size.value=2*Math.round(clamp(drag.s+2*(e.clientX-drag.x)*scale,320,max)/2);}else{const half=Number(f.elements.size.value)/2+b;f.elements.x.value=Math.round(clamp(drag.ox+(e.clientX-drag.x)*scale,Math.max(-380,half-540),Math.min(380,540-half)));f.elements.y.value=Math.round(clamp(drag.oy+(e.clientY-drag.y)*scale,Math.max(-650,half-960),Math.min(650,960-half)));}f.dispatchEvent(new Event('input',{bubbles:true}));});
for(const ev of ['pointerup','pointercancel','lostpointercapture'])m.addEventListener(ev,()=>drag=null);
const ad=document.getElementById('studio-ad'),img=document.getElementById('studio-ad-image'),movie=document.getElementById('studio-ad-video'),caption=document.getElementById('studio-caption');
const field=k=>f.elements[k],num=k=>Number(field(k).value);
function campaign(){const opt=field('preview_campaign').selectedOptions[0];return opt?.dataset.spec?JSON.parse(opt.dataset.spec):null;}
function layout(){const c=campaign();if(field('ad_override').value==='1')return Object.fromEntries(['width','height','x','y','opacity'].map(k=>[k,num('ad_'+k)]));if(!c)return null;return {...c,x:c.x||0,y:({top:c.margin+c.height/2-960,center:0,bottom:960-c.margin-c.height/2}[c.position])+(c.y||0)};}
function drawLayers(){
 const c=campaign(),a=layout();ad.hidden=!c||!a;
 if(c&&a){const src='/campaigns/'+field('preview_campaign').selectedOptions[0].dataset.index+'/media',motion=/\.(mp4|webm|mov)$/i.test(c.path);img.hidden=motion;movie.hidden=!motion;if(motion){if(movie.getAttribute('src')!==src){movie.src=src;movie.play().catch(()=>{});}}else{movie.pause();if(img.getAttribute('src')!==src)img.src=src;}
 Object.assign(ad.style,{width:a.width/1080*100+'%',height:a.height/1920*100+'%',left:50+a.x/1080*100+'%',top:50+a.y/1920*100+'%',opacity:a.opacity??1});}else movie.pause();
 caption.hidden=!field('preview_captions').checked;caption.style.color=field('sub_color').value;caption.style.fontFamily=field('sub_font').value;caption.style.fontSize=num('sub_size')*p.clientWidth/1080+'px';caption.style.textShadow='0 1px 3px '+field('sub_outline_color').value;caption.style.top=({2:100-num('sub_margin')/1920*100,5:50,8:num('sub_margin')/1920*100}[num('sub_alignment')])+'%';
}
let adDrag=null;
ad.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();layer('ad');const a=layout();if(!a)return;for(const k of ['width','height','x','y'])field('ad_'+k).value=Math.round(a[k]);field('ad_opacity').value=a.opacity??1;if(field('ad_override').value!=='1'){const c=campaign();field('ad_start').value=c.start??0;field('ad_end').value=c.end??'';}field('ad_override').value='1';ad.setPointerCapture(e.pointerId);adDrag={...a,px:e.clientX,py:e.clientY,resize:e.target.id==='studio-ad-grip'};});
ad.addEventListener('pointermove',e=>{if(!adDrag)return;const s=1080/p.clientWidth,dx=(e.clientX-adDrag.px)*s,dy=(e.clientY-adDrag.py)*s,clamp=(n,l,h)=>Math.round(Math.max(l,Math.min(h,n)));if(adDrag.resize){field('ad_width').value=clamp(adDrag.width+2*dx,40,1080-2*Math.abs(adDrag.x));field('ad_height').value=clamp(adDrag.height+2*dy,40,1920-2*Math.abs(adDrag.y));}else{field('ad_x').value=clamp(adDrag.x+dx,adDrag.width/2-540,540-adDrag.width/2);field('ad_y').value=clamp(adDrag.y+dy,adDrag.height/2-960,960-adDrag.height/2);}drawLayers();});
for(const ev of ['pointerup','pointercancel','lostpointercapture'])ad.addEventListener(ev,()=>adDrag=null);
f.addEventListener('input',drawLayers);f.addEventListener('change',drawLayers);window.addEventListener('resize',drawLayers);window.addEventListener('workspace-change',drawLayers);
document.querySelectorAll('.edit-profile').forEach(b=>b.addEventListener('click',()=>{const a=JSON.parse(b.dataset.spec).ad_layout;field('ad_override').value=a?'1':'0';if(a)for(const [k,v] of Object.entries(a))field('ad_'+k).value=v??'';drawLayers();}));
drawLayers();
window.addEventListener('pagehide',()=>{if(url)URL.revokeObjectURL(url);});
})();