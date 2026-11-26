"""Local production settings, separate from social API credentials."""
import json
import re
from pathlib import Path

def load(root):
    path=Path(root)/'production-profiles.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

def save(root,name,form,templates,campaigns):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,48}',name): raise ValueError('Invalid profile name')
    platform=form.get('platform','instagram')
    if platform not in ('instagram','youtube','vk','tiktok','telegram','other'): raise ValueError('Invalid platform')
    template=form.get('template','')
    if template not in templates: raise ValueError('Choose an existing template')
    campaign=form.get('campaign','')
    if campaign and campaign not in campaigns: raise ValueError('Unknown campaign')
    handle=form.get('handle','').strip()
    if len(handle)>100: raise ValueError('Handle too long')
    font_size=int(form.get('font_size',64))
    margin=int(form.get('caption_margin',480))
    if not 20<=font_size<=120 or not 0<=margin<=1400: raise ValueError('Invalid subtitles')
    from caption_style import from_form
    caption_style=from_form(form)
    if 'sub_size' not in form: caption_style['size']=font_size
    if 'sub_margin' not in form: caption_style['margin']=margin
    cover_mode=form.get('cover_mode','auto')
    cover_title=form.get('cover_title','').strip()
    cover_color=form.get('cover_color','#172536')
    if cover_mode not in ('auto','first','middle','branded','off') or len(cover_title)>80 or not re.fullmatch(r'#[0-9a-fA-F]{6}',cover_color): raise ValueError('Invalid cover settings')
    daily_limit=int(form.get('daily_limit',10))
    priority=int(form.get('priority',1))
    if not 1<=daily_limit<=1000 or not 1<=priority<=10: raise ValueError('Invalid production quota')
    profiles=load(root)
    if len(profiles)>=100 and name not in profiles: raise ValueError('Profile limit')
    profiles[name]=dict(platform=platform,handle=handle,template=template,campaign=campaign,
        captions=form.get('captions')=='1',caption_style=caption_style,font_size=font_size,caption_margin=margin,cover_mode=cover_mode,cover_title=cover_title,cover_color=cover_color,daily_limit=daily_limit,priority=priority,enabled=form.get('enabled','1')=='1')
    path=Path(root)/'production-profiles.json'
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(profiles,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)
    return profiles[name]
