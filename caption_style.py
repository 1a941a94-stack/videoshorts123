import re

DEFAULT=dict(font='Arial',size=64,margin=480,color='#ffffff',highlight='#ffd500',outline_color='#000000',outline=5,shadow=1,words=4,alignment=2,karaoke=True)

def validate(data):
    style={**DEFAULT,**{k:data[k] for k in DEFAULT if k in data}}
    if not re.fullmatch(r'[\w .-]{1,60}',style['font']): raise ValueError('Invalid font')
    for k,low,high in [('size',20,120),('margin',0,1400),('outline',0,15),('shadow',0,10),('words',1,8)]:
        style[k]=int(style[k])
        if not low<=style[k]<=high: raise ValueError('Invalid caption '+k)
    style['alignment']=int(style['alignment'])
    if style['alignment'] not in (2,5,8): raise ValueError('Invalid alignment')
    for k in ('color','highlight','outline_color'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',style[k]): raise ValueError('Invalid caption color')
    style['karaoke']=style['karaoke'] in (True,1,'1','true','on')
    return style

def bgr(color):
    return ''.join(reversed([color[1:3],color[3:5],color[5:7]])).upper()

def from_form(form):
    return validate({k:form['sub_'+k] for k in DEFAULT if 'sub_'+k in form})

def from_account(account):
    return validate(account.get('caption_style',{'size':account.get('font_size',64),'margin':account.get('caption_margin',480)}))
