"""Production sessions for ClipFactory 2.0; independent of publication accounts."""
import json
import time
from contextlib import contextmanager
from pathlib import Path
import os

ENV_KEYS=('CLIP_SHORT_TEMPLATE','CLIP_SHORT_LAYOUT','CLIP_SHORT_BACKGROUND','CLIP_CAPTIONS','CLIP_CAPTION_STYLE','CLIP_FONT_SIZE','CLIP_CAPTION_MARGIN','CLIP_CAMPAIGN_NAME','CLIP_COVER_MODE','CLIP_COVER_TITLE','CLIP_COVER_COLOR','CLIP_ENCODER','CLIP_NORMALIZE_AUDIO','CLIP_SMART_SPEECH','CLIP_PRODUCTION_PROFILE')

def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS production_runs(
        id INTEGER PRIMARY KEY, created INTEGER NOT NULL, finished INTEGER,
        goal INTEGER NOT NULL CHECK(goal BETWEEN 1 AND 1000),
        mode TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
        snapshot TEXT NOT NULL, reason TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS production_run_tasks(
        run_id INTEGER NOT NULL REFERENCES production_runs(id),
        clip_id INTEGER NOT NULL REFERENCES clips(id),
        status TEXT NOT NULL, updated INTEGER NOT NULL,
        PRIMARY KEY(run_id,clip_id))""")

def snapshot(mode,campaigns=None):
    if mode not in ('short','long'): raise ValueError('Invalid mode')
    return {'mode':mode,'env':{k:os.environ.get(k) for k in ENV_KEYS},
            'campaigns':str(Path(campaigns).resolve()) if campaigns else None}

def create(db,goal,config):
    if not 1<=int(goal)<=1000 or config['mode'] not in ('short','long'): raise ValueError('Invalid run settings')
    with db:
        return db.execute('INSERT INTO production_runs(created,goal,mode,snapshot) VALUES(?,?,?,?)',
            (int(time.time()),int(goal),config['mode'],json.dumps(config,ensure_ascii=False))).lastrowid

def set_status(db,run_id,status,reason=None):
    if status not in ('queued','running','completed','exhausted','stopped','failed','paused'): raise ValueError('Invalid run status')
    finished=int(time.time()) if status in ('completed','exhausted','stopped','failed') else None
    with db: db.execute('UPDATE production_runs SET status=?,finished=?,reason=? WHERE id=?',(status,finished,reason,run_id))

def record(db,run_id,clip_id,status):
    with db:
        db.execute("""INSERT INTO production_run_tasks(run_id,clip_id,status,updated) VALUES(?,?,?,?)
            ON CONFLICT(run_id,clip_id) DO UPDATE SET status=excluded.status,updated=excluded.updated""",
            (run_id,clip_id,status,int(time.time())))

def summary(db,run_id):
    row=db.execute('SELECT * FROM production_runs WHERE id=?',(run_id,)).fetchone()
    if not row: raise ValueError('Unknown run')
    data=dict(row)
    data['snapshot']=json.loads(data['snapshot'])
    data['counts']=dict(db.execute('SELECT status,count(*) FROM production_run_tasks WHERE run_id=? GROUP BY status',(run_id,)))
    return data

@contextmanager
def apply(config):
    old={k:os.environ.get(k) for k in ENV_KEYS}
    try:
        for k in ENV_KEYS:
            value=config['env'].get(k)
            if value is None: os.environ.pop(k,None)
            else: os.environ[k]=str(value)
        yield
    finally:
        for k,v in old.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k]=v
