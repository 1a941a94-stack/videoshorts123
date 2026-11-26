(() => {
const f=document.getElementById('template-form'), p=document.getElementById('template-preview'), m=document.getElementById('preview-mask');
if(!f||!p||!m)return;
const v=k=>f.elements[k].value;
function draw(){
 const size=Number(v('size')),x=Number(v('x')),y=Number(v('y')),b=Number(v('border'));
 p.style.backgroundColor=v('color');
 p.style.backgroundImage=v('background')?'url("/short-backgrounds/'+encodeURIComponent(v('background'))+'")':'none';
 m.style.width=(size+2*b)/1080*100+'%';
 m.style.left=(50+x/1080*100)+'%';
 m.style.top=(50+y/1920*100)+'%';
 m.style.borderRadius=v('layout')==='circle'?'50%':'0';
 m.style.border=b/1080*p.clientWidth+'px solid '+v('border_color');
 m.textContent=v('fit')==='cover'?'ЗАПОЛНЕНИЕ':'ВПИСАТЬ';
}
f.addEventListener('input',draw);
window.addEventListener('resize',draw);
document.querySelectorAll('.edit-profile').forEach(btn=>btn.addEventListener('click',()=>{
 const data=JSON.parse(btn.dataset.spec);
 f.elements.name.value=btn.dataset.name;
 for(const [k,val] of Object.entries(data))if(f.elements[k])f.elements[k].value=val;
 draw(); f.scrollIntoView({behavior:'smooth',block:'center'});
}));
draw();
})();
