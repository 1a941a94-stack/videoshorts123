"""Version history for rendered media; original source files are never changed."""
import time
from pathlib import Path

def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS clip_versions(
        id INTEGER PRIMARY KEY, clip_id INTEGER NOT NULL REFERENCES clips(id),
        output TEXT NOT NULL, cover TEXT, created INTEGER NOT NULL,
        campaign TEXT, quality_result TEXT, actual_start REAL, actual_end REAL,
        UNIQUE(clip_id,output))""")

def remember(db,row):
    if row['output']:
        db.execute("""INSERT OR IGNORE INTO clip_versions(clip_id,output,cover,created,campaign,quality_result,actual_start,actual_end)
        VALUES(?,?,?,?,?,?,?,?)""",(row['id'],row['output'],row['cover'],int(time.time()),row['campaign'],row['quality_result'],row['actual_start'],row['actual_end']))

def list_versions(db,root,cid):
    out=(Path(root)/'output').resolve()
    rows=db.execute('SELECT * FROM clip_versions WHERE clip_id=? ORDER BY id DESC',(cid,)).fetchall()
    result=[]
    for r in rows:
        p=(Path(root)/r['output']).resolve()
        if p.is_relative_to(out) and p.is_file() and p.suffix=='.mp4':
            result.append(dict(id=r['id'],created=r['created'],campaign=r['campaign'],bytes=p.stat().st_size))
    return result

def media(db,root,cid,vid):
    row=db.execute('SELECT output FROM clip_versions WHERE clip_id=? AND id=?',(cid,vid)).fetchone()
    if not row: return None
    p=(Path(root)/row['output']).resolve()
    if p.is_relative_to((Path(root)/'output').resolve()) and p.is_file() and p.suffix=='.mp4': return p
    return None
