(() => {
const f=document.getElementById('template-form'),p=document.getElementById('template-preview'),m=document.getElementById('preview-mask'),v=document.getElementById('studio-source');
if(!f||!v)return;
const groups={video:['layout','size','x','y','border','border_color','fit','preview_source'],background:['color','background'],ad:['preview_campaign'],captions:['preview_captions','sub_size','sub_margin','sub_font','sub_color','sub_highlight','sub_outline_color','sub_outline','sub_shadow','sub_words','sub_alignment','sub_karaoke']};
function layer(key){document.querySelectorAll('[data-layer]').forEach(b=>b.classList.toggle('active',b.dataset.layer===key));for(const l of f.querySelectorAll('label')){const input=l.querySelector('[name]');l.hidden=!!input&&input.name!=='name'&&key!=='all'&&!groups[key].includes(input.name);}}
document.querySelectorAll('[data-layer]').forEach(b=>b.addEventListener('click',()=>layer(b.dataset.layer)));
layer('video');
let url='';
f.elements.preview_source.addEventListener('change',()=>{if(url)URL.revokeObjectURL(url);const file=f.elements.preview_source.files[0];if(file){url=URL.createObjectURL(file);v.src=url;v.play().catch(()=>{});}else{v.removeAttribute('src');v.load();}});
let drag=null;
m.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();layer('video');m.setPointerCapture(e.pointerId);drag={id:e.pointerId,x:e.clientX,y:e.clientY,s:Number(f.elements.size.value),ox:Number(f.elements.x.value),oy:Number(f.elements.y.value),resize:e.target.id==='studio-grip'};});
m.addEventListener('pointermove',e=>{if(!drag||e.pointerId!==drag.id)return;const scale=1080/p.clientWidth,b=Number(f.elements.border.value);const clamp=(x,a,z)=>Math.min(z,Math.max(a,x));if(drag.resize){const max=Math.min(1080-2*Math.abs(drag.ox),1920-2*Math.abs(drag.oy))-2*b;f.elements.size.value=2*Math.round(clamp(drag.s+2*(e.clientX-drag.x)*scale,320,max)/2);}else{const half=Number(f.elements.size.value)/2+b;f.elements.x.value=Math.round(clamp(drag.ox+(e.clientX-drag.x)*scale,Math.max(-380,half-540),Math.min(380,540-half)));f.elements.y.value=Math.round(clamp(drag.oy+(e.clientY-drag.y)*scale,Math.max(-650,half-960),Math.min(650,960-half)));}f.dispatchEvent(new Event('input',{bubbles:true}));});
for(const ev of ['pointerup','pointercancel','lostpointercapture'])m.addEventListener(ev,()=>drag=null);
window.addEventListener('pagehide',()=>{if(url)URL.revokeObjectURL(url);});
})();