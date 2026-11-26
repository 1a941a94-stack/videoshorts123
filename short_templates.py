"""Validated local template profiles for 1080x1920 output."""
import json
import re
from pathlib import Path

DEFAULT=dict(layout='circle',size=960,x=0,y=80,color='#172536',background='',border=0,border_color='#ffffff',fit='cover',auto_crop=True)

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
    out['auto_crop']=out['auto_crop'] in (True,1,'1','true','on')
    from caption_style import validate as validate_style,from_form
    if 'caption_style' in data: out['caption_style']=validate_style(data['caption_style'])
    elif any(k.startswith('sub_') for k in data): out['caption_style']=from_form(data)
    if 'ad_layout' in data or data.get('ad_override')=='1':
        raw=data.get('ad_layout') or {k:data['ad_'+k] for k in ('width','height','x','y','opacity','start','end')}
        ad={k:int(raw[k]) for k in ('width','height','x','y')}
        ad.update(opacity=float(raw['opacity']),start=float(raw['start']),end=float(raw['end']) if raw.get('end') not in (None,'') else None)
        import math
        if not 1<=ad['width']<=1080 or not 1<=ad['height']<=1920 or abs(ad['x'])+ad['width']/2>540 or abs(ad['y'])+ad['height']/2>960: raise ValueError('Banner outside canvas')
        if not math.isfinite(ad['opacity']) or not 0<=ad['opacity']<=1 or not math.isfinite(ad['start']) or ad['start']<0 or (ad['end'] is not None and (not math.isfinite(ad['end']) or ad['end']<=ad['start'])): raise ValueError('Invalid banner timing or opacity')
        out['ad_layout']=ad
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
