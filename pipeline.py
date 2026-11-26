"""Persistent discovery queue for ClipFactory. No background service required."""
import argparse
import json
import sqlite3
import time
from pathlib import Path
from clipfactory import extract, select, download, render

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 id INTEGER PRIMARY KEY, query TEXT UNIQUE NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 last_scan INTEGER
);
CREATE TABLE IF NOT EXISTS videos (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT, views INTEGER, duration REAL,
 status TEXT NOT NULL, checked INTEGER NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS clips (
 id INTEGER PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(id),
 start REAL NOT NULL, end REAL NOT NULL, score REAL NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 updated INTEGER NOT NULL, error TEXT, output TEXT,
 UNIQUE(video_id,start,end)
);
CREATE INDEX IF NOT EXISTS clips_queue ON clips(status,score DESC);
"""

def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    if 'campaign' not in {r[1] for r in db.execute('PRAGMA table_info(clips)')}:
        db.execute('ALTER TABLE clips ADD COLUMN campaign TEXT')
        db.commit()
    return db

def add_source(db, query):
    with db:
        db.execute("INSERT OR IGNORE INTO sources(query) VALUES (?)", (query,))

def discover(query, limit):
    import yt_dlp
    target = query if query.startswith("https://www.youtube.com/") else f"ytsearch{limit}:{query}"
    with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'playlistend': limit}) as ydl:
        data = ydl.extract_info(target, download=False)
        return list(data.get('entries') or [])

def inspect_video(db, entry, settings, extractor=extract):
    vid = entry.get('id')
    if not vid or len(vid)!=11 or not all(c.isalnum() or c in '-_' for c in vid):
        return 'invalid'
    url = 'https://www.youtube.com/watch?v=' + vid
    now = int(time.time())
    old = db.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if old and now-old['checked'] < settings['refresh_hours']*3600:
        return 'cached'
    info = {}
    try:
        info = extractor(url)
        duration = info.get('duration') or 0
        views = info.get('view_count') or 0
        if info.get('is_live') or not settings['min_duration'] <= duration <= settings['max_duration'] or views < settings['min_views']:
            status, clips = 'filtered', []
        else:
            clips = select(info, settings['length'], settings['count'], settings['threshold'])
            status = 'ready' if clips else 'no_peaks'
        error = None
    except Exception as exc:
        status, clips, error = 'error', [], str(exc)[:1000]
    with db:
        db.execute("""INSERT INTO videos(id,url,title,views,duration,status,checked,error)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
        views=excluded.views,duration=excluded.duration,status=excluded.status,
        checked=excluded.checked,error=excluded.error""",
        (vid,url,info.get('title'),info.get('view_count'),info.get('duration'),status,now,error))
        for c in clips:
            db.execute("""INSERT OR IGNORE INTO clips(video_id,start,end,score,updated)
            SELECT ?,?,?,?,? WHERE NOT EXISTS
            (SELECT 1 FROM clips WHERE video_id=? AND start < ? AND end > ?)""",
            (vid,c['start'],c['end'],c['score'],now,vid,c['end'],c['start']))
    return status

def scan(db, settings, finder=discover, extractor=extract):
    counts = {}
    for src in db.execute("SELECT * FROM sources WHERE enabled=1").fetchall():
        try:
            entries = finder(src['query'], settings['limit'])
            for entry in entries:
                if not entry: continue
                status = inspect_video(db,entry,settings,extractor)
                counts[status] = counts.get(status,0)+1
                if status != 'cached': time.sleep(settings['delay'])
            with db:
                db.execute("UPDATE sources SET last_scan=? WHERE id=?", (int(time.time()),src['id']))
        except Exception as exc:
            print(json.dumps({'source':src['query'],'error':str(exc)},ensure_ascii=False))
    return counts

def claim(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("""SELECT c.*,v.url FROM clips c JOIN videos v ON v.id=c.video_id
        WHERE c.status='pending' ORDER BY c.score DESC,c.id LIMIT 1""").fetchone()
        if row:
            db.execute("UPDATE clips SET status='running',attempts=attempts+1,updated=? WHERE id=?", (int(time.time()),row['id']))
        db.commit()
        return row
    except BaseException:
        db.rollback()
        raise

def process(db, out, banner=None, campaigns=None):
    row = claim(db)
    if row is None: return False
    out.mkdir(parents=True,exist_ok=True)
    raw = out / f"raw_{row['id']}.mp4"
    dest = out / f"clip_{row['id']}.mp4"
    tmp = out / f"clip_{row['id']}.partial.mp4"
    try:
        from banners import choose
        selected=choose(campaigns,row['end']-row['start']) if campaigns else banner
        download(row['url'],dict(row),raw)
        render(raw,0,row['end']-row['start'],tmp,selected)
        tmp.replace(dest)
        with db:
            db.execute("UPDATE clips SET status='done',output=?,error=NULL,updated=?,campaign=? WHERE id=?", (str(dest),int(time.time()),getattr(selected,'name','manual') if selected else None,row['id']))
    except Exception as exc:
        with db:
            db.execute("UPDATE clips SET status='failed',error=?,updated=? WHERE id=?", (str(exc)[:1000],int(time.time()),row['id']))
    finally:
        raw.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    return True

DEFAULTS = dict(limit=20,min_views=10000,min_duration=120,max_duration=10800,
                length=45,count=3,threshold=.7,refresh_hours=24,delay=2)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db',default='clipfactory.sqlite3')
    ap.add_argument('--config',type=Path)
    sub=ap.add_subparsers(dest='action',required=True)
    sub.add_parser('add').add_argument('query')
    sub.add_parser('scan')
    sub.add_parser('status')
    sub.add_parser('retry')
    work=sub.add_parser('work')
    work.add_argument('--limit',type=int,default=10)
    work.add_argument('--out',type=Path,default=Path('output'))
    ads=work.add_mutually_exclusive_group()
    ads.add_argument('--banner',type=Path)
    ads.add_argument('--campaigns',type=Path)
    args=ap.parse_args()
    settings=DEFAULTS.copy()
    if args.config:
        settings.update(json.loads(args.config.read_text(encoding='utf-8')))
    if settings['limit']<=0 or settings['length']<=0 or settings['count']<=0 or settings['delay']<0 or settings['refresh_hours']<0 or not 0<=settings['threshold']<=1:
        ap.error('Invalid settings')
    db=connect(args.db)
    try:
        if args.action=='add': add_source(db,args.query)
        elif args.action=='scan': print(json.dumps(scan(db,settings),ensure_ascii=False))
        elif args.action=='work':
            for _ in range(args.limit):
                if not process(db,args.out,args.banner,args.campaigns): break
        elif args.action=='retry':
            with db:
                db.execute("UPDATE clips SET status='pending',updated=? WHERE status='failed' AND attempts<3",(int(time.time()),))
        elif args.action=='status':
            for table in ('videos','clips'):
                print(table,dict(db.execute(f"SELECT status,COUNT(*) FROM {table} GROUP BY status").fetchall()))
    finally: db.close()

if __name__=='__main__': main()
