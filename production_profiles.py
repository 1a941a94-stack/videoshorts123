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
    profiles=load(root)
    if len(profiles)>=100 and name not in profiles: raise ValueError('Profile limit')
    profiles[name]=dict(platform=platform,handle=handle,template=template,campaign=campaign,
        captions=form.get('captions')=='1',font_size=font_size,caption_margin=margin)
    path=Path(root)/'production-profiles.json'
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(profiles,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)
    return profiles[name]
