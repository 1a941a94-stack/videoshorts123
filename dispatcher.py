"""Sequential short production under pipeline's exclusive production lock."""
import os
import json
import time
import shutil
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from production_profiles import load
from short_templates import load as load_templates,validate
from source_media import stage

def day_start():
    return int(datetime.now().replace(hour=0,minute=0,second=0,microsecond=0).timestamp())

def select_profile(profiles,counts):
    eligible=[(name,p) for name,p in profiles.items() if p.get('enabled',True) and counts.get(name,0)<p.get('daily_limit',10)]
    if not eligible: return None
    return min(eligible,key=lambda item:(counts.get(item[0],0)/item[1].get('daily_limit',10)/item[1].get('priority',1),-item[1].get('priority',1),item[0]))[0]

@contextmanager
def profile_env(root,name,account,templates):
    spec=validate(templates[account['template']])
    values={'CLIP_PRODUCTION_PROFILE':name,'CLIP_SHORT_TEMPLATE':json.dumps(spec),
        'CLIP_CAPTIONS':'1' if account['captions'] else '0','CLIP_FONT_SIZE':str(account['font_size']),
        'CLIP_CAPTION_MARGIN':str(account['caption_margin']),'CLIP_CAMPAIGN_NAME':account['campaign'],
        'CLIP_COVER_MODE':account.get('cover_mode','auto'),'CLIP_COVER_TITLE':account.get('cover_title') or account.get('handle',''),
        'CLIP_COVER_COLOR':account.get('cover_color','#172536'),'CLIP_SHORT_BACKGROUND':''}
    if spec['background']:
        path=root/'assets'/'backgrounds'/spec['background']
        if not path.is_file(): raise ValueError('Background missing')
        values['CLIP_SHORT_BACKGROUND']=str(path)
    old={k:os.environ.get(k) for k in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for k,v in old.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k]=v

def run(db,root,out,limit=100,continuous=False,replenish=False,interval=1800):
    from pipeline import process
    from telegram_source import scan_library
    root=Path(root).resolve()
    out=Path(out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    stop=root/'factory.stop'
    profiles=load(root)
    templates=load_templates(root)
    campaigns=root/'campaigns.json'
    if not profiles: raise ValueError('Create production profiles first')
    if not 1<=limit<=1000 or interval<60: raise ValueError('Invalid dispatcher limits')
    attempts=0
    next_scan=0
    blocked=set()
    print(f'CF_PROGRESS 0 {limit}',flush=True)
    while not stop.exists():
        counts=dict(db.execute("SELECT production_profile,count(*) FROM clips WHERE status='done' AND updated>=? GROUP BY production_profile",(day_start(),)))
        name=select_profile({k:v for k,v in profiles.items() if k not in blocked},counts)
        pending=db.execute("SELECT count(*) FROM clips WHERE status='pending' AND mode='short'").fetchone()[0]
        if name and pending and shutil.disk_usage(out).free>=3*1024**3:
            account=profiles[name]
            stage('dispatch',f'{name}: {counts.get(name,0)}/{account.get("daily_limit",10)}')
            try:
                with profile_env(root,name,account,templates):
                    if not process(db,out,campaigns=campaigns if account['campaign'] else None,mode='short'): break
            except (ValueError,KeyError,OSError) as exc:
                blocked.add(name)
                stage('error',f'{name}: {exc}')
                continue
            attempts+=1
            print(f'CF_PROGRESS {attempts} {limit}',flush=True)
            if attempts>=limit: break
            continue
        if name and not pending and replenish and time.monotonic()>=next_scan:
            next_scan=time.monotonic()+interval
            if scan_library(db,root): break
            continue
        if not continuous: break
        if not name and blocked: break
        stage('dispatch','Waiting for queue, quota or free disk')
        for _ in range(30):
            if stop.exists(): break
            time.sleep(1)
    stage('dispatch',f'Stopped; processed {attempts} candidates')
