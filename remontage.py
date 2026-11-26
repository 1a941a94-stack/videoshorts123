"""Edit a single short without changing shared production settings."""
import json
import time
from pathlib import Path
from short_templates import validate
from run_configs import resolve

def settings(root,row):
    saved=json.loads(row['task_snapshot']) if row['task_snapshot'] else None
    if saved:
        env=saved['env']
        spec=validate(json.loads(env.get('CLIP_SHORT_TEMPLATE') or '{}'))
        return dict(template=spec,campaign=env.get('CLIP_CAMPAIGN_NAME') or row['campaign'] or '',captions=env.get('CLIP_CAPTIONS')=='1',known=True)
    return dict(template=validate({'fit':'cover'}),campaign=row['campaign'] or '',captions=False,known=False)

def prepare(root,db,cid,form):
    row=db.execute('SELECT * FROM clips WHERE id=?',(cid,)).fetchone()
    if not row or row['mode']!='short' or not row['output'] or row['status'] not in ('done','failed','ad_review','ad_rejected','duplicate'):
        raise ValueError('Недоступен повторный монтаж')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publications'").fetchone():
        if db.execute('SELECT 1 FROM publications WHERE clip_id=? LIMIT 1',(cid,)).fetchone():
            raise ValueError('У видео есть записи публикации')
    previous=settings(root,row)['template']
    spec=validate({**previous,**dict(form)})
    campaign=form.get('campaign','')
    captions=form.get('captions')=='1'
    cfg=resolve(root,dict(mode='short',template='',campaign=campaign,captions=captions,auto_search=False))
    if row['task_snapshot']:
        old=json.loads(row['task_snapshot'])['env']
        for key in ('CLIP_CAPTION_STYLE','CLIP_FONT_SIZE','CLIP_CAPTION_MARGIN','CLIP_COVER_MODE','CLIP_COVER_TITLE','CLIP_COVER_COLOR','CLIP_PRODUCTION_PROFILE'):
            if old.get(key) is not None: cfg['env'][key]=old[key]
    cfg['env']['CLIP_SHORT_TEMPLATE']=json.dumps(spec)
    cfg['env']['CLIP_SHORT_LAYOUT']=spec['layout']
    if spec['background']:
        p=Path(root)/'assets'/'backgrounds'/spec['background']
        if not p.is_file(): raise ValueError('Фон не найден')
        cfg['env']['CLIP_SHORT_BACKGROUND']=str(p.resolve())
    cfg.update(only_ids=[cid],name='Повторный монтаж #'+str(cid))
    with db:
        run_id=db.execute('INSERT INTO production_runs(created,goal,mode,snapshot) VALUES(?,?,?,?)',(int(time.time()),1,'short',json.dumps(cfg,ensure_ascii=False))).lastrowid
        db.execute("UPDATE clips SET status='pending',run_id=?,task_snapshot=?,attempts=0,error=NULL WHERE id=?",(run_id,json.dumps(cfg,ensure_ascii=False),cid))
    return run_id
