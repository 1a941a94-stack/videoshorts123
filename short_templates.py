"""Validated local template profiles for 1080x1920 output."""
import json
import re
from pathlib import Path

DEFAULT=dict(layout='circle',size=960,x=0,y=80,color='#172536',background='',border=0,border_color='#ffffff',fit='contain')

def validate(data):
    out={**DEFAULT,**{k:data[k] for k in DEFAULT if k in data}}
    if out['layout'] not in ('circle','rectangle') or out['fit'] not in ('contain','cover'): raise ValueError('Invalid layout')
    for k,lo,hi in [('size',320,1080),('x',-380,380),('y',-650,650),('border',0,24)]:
        out[k]=int(out[k])
        if not lo<=out[k]<=hi: raise ValueError(f'Invalid {k}')
    out['size']-=out['size']%2
    if abs(out['x'])+out['size']/2+out['border']>540 or abs(out['y'])+out['size']/2+out['border']>960:
        raise ValueError('Video must fit canvas')
    for k in ('color','border_color'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',out[k]): raise ValueError('Invalid color')
    if out['background'] and not re.fullmatch(r'[a-f0-9]{24}\.(?:jpg|mp4|webm|mov|gif)',out['background']): raise ValueError('Invalid background ID')
    return out

def load(root):
    p=Path(root)/'short-templates.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else {}

def save(root,name,data):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',name): raise ValueError('Invalid template name')
    root=Path(root)
    spec=validate(data)
    if spec['background'] and not (root/'assets'/'backgrounds'/spec['background']).is_file(): raise ValueError('Background missing')
    profiles=load(root)
    if len(profiles)>=100 and name not in profiles: raise ValueError('Template limit')
    profiles[name]=spec
    p=root/'short-templates.json'
    temp=p.with_suffix('.tmp')
    temp.write_text(json.dumps(profiles,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(p)
    return spec
