"""Persistent discovery queue for ClipFactory. No background service required."""
import argparse
import json
import os
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
CREATE TABLE IF NOT EXISTS telegram_channels (name TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, history INTEGER NOT NULL DEFAULT 100, min_views INTEGER NOT NULL DEFAULT 0, cursor INTEGER, last_scan INTEGER, found INTEGER NOT NULL DEFAULT 0, error TEXT);
CREATE TABLE IF NOT EXISTS fingerprints (clip_id INTEGER PRIMARY KEY REFERENCES clips(id), sha256 TEXT NOT NULL, duration REAL NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS fingerprints_duration ON fingerprints(duration);
CREATE INDEX IF NOT EXISTS fingerprints_sha ON fingerprints(sha256);
CREATE INDEX IF NOT EXISTS clips_queue ON clips(status,score DESC);
"""

def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    db.execute('BEGIN IMMEDIATE')
    try:
        cols={r[1] for r in db.execute('PRAGMA table_info(clips)')}
        for name,kind in [('campaign','TEXT'),('peak','REAL'),('rank','REAL'),('actual_start','REAL'),('actual_end','REAL'),('boundary_method','TEXT'),('mode',"TEXT NOT NULL DEFAULT 'long'"),('authorized','INTEGER NOT NULL DEFAULT 0'),('duplicate_of','INTEGER'),('duplicate_kind','TEXT'),('ad_result','TEXT'),('production_profile','TEXT'),('cover','TEXT'),('cover_error','TEXT')]:
            if name not in cols: db.execute(f'ALTER TABLE clips ADD COLUMN {name} {kind}')
        db.commit()
    except BaseException:
        db.rollback()
        raise
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

def inspect_video(db, entry, settings, extractor=extract, mode='long'):
    vid = entry.get('id')
    if not vid or len(vid)!=11 or not all(c.isalnum() or c in '-_' for c in vid):
        return 'invalid'
    url = 'https://www.youtube.com/watch?v=' + vid
    now = int(time.time())
    old = db.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if old and mode=='long' and now-old['checked'] < settings['refresh_hours']*3600:
        return 'cached'
    info = {}
    try:
        info = extractor(url)
        duration = info.get('duration') or 0
        views = info.get('view_count') or 0
        if mode=='short':
            from short_media import candidate
            clips=candidate(info,settings['min_views'])
            status='ready' if clips else 'filtered'
        elif info.get('is_live') or not settings['min_duration'] <= duration <= settings['max_duration'] or views < settings['min_views']:
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
            db.execute("""INSERT OR IGNORE INTO clips(video_id,start,end,score,updated,peak,rank,mode)
            SELECT ?,?,?,?,?,?,?,? WHERE NOT EXISTS
            (SELECT 1 FROM clips WHERE video_id=? AND start < ? AND end > ?)""",
            (vid,c['start'],c['end'],c['score'],now,c.get('peak'),c.get('rank'),mode,vid,c['end'],c['start']))
    return status

def scan(db, settings, finder=discover, extractor=extract, mode='long'):
    counts = {}
    sources=db.execute("SELECT * FROM sources WHERE enabled=1").fetchall() if mode=='long' else [{'query':q,'id':None} for q in ('смешные короткие видео shorts','мемы приколы shorts','смешные животные shorts','funny unexpected moments shorts')]
    print(f'CF_PROGRESS 0 {len(sources)}',flush=True)
    for i,src in enumerate(sources,1):
        print('CF_STAGE '+json.dumps({'stage':'search','detail':src['query']},ensure_ascii=True),flush=True)
        try:
            entries = finder(src['query'], settings['limit'])
            for j,entry in enumerate(entries,1):
                if not entry: continue
                print('CF_STAGE '+json.dumps({'stage':'inspect','detail':f'{src["query"]} · {j}/{len(entries)}'},ensure_ascii=True),flush=True)
                status = inspect_video(db,entry,settings,extractor,mode)
                counts[status] = counts.get(status,0)+1
                if status != 'cached': time.sleep(settings['delay'])
            with db:
                db.execute("UPDATE sources SET last_scan=? WHERE id=?", (int(time.time()),src['id']))
        except Exception as exc:
            print(json.dumps({'source':src['query'],'error':str(exc)},ensure_ascii=False))
        print(f'CF_PROGRESS {i} {len(sources)}',flush=True)
    return counts

def approve_short(db,cid):
    with db:
        return db.execute("UPDATE clips SET authorized=1 WHERE id=? AND mode='short' AND status='pending'",(cid,)).rowcount

def claim(db,mode='long'):
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("""SELECT c.*,v.url FROM clips c JOIN videos v ON v.id=c.video_id
        WHERE c.status='pending' AND c.mode=? ORDER BY coalesce(c.rank,c.score) DESC,c.id LIMIT 1""",(mode,)).fetchone()
        if row:
            db.execute("UPDATE clips SET status='running',attempts=attempts+1,updated=? WHERE id=?", (int(time.time()),row['id']))
        db.commit()
        return row
    except BaseException:
        db.rollback()
        raise

def process(db, out, banner=None, campaigns=None, mode='long'):
    row = claim(db,mode)
    if row is None: return False
    profile=os.getenv('CLIP_PRODUCTION_PROFILE','') if mode=='short' else ''
    if profile:
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',profile): raise ValueError('Invalid production profile')
    cache_root=out
    if profile: out=out/'profiles'/profile
    out.mkdir(parents=True,exist_ok=True)
    with db:
        db.execute("UPDATE clips SET production_profile=? WHERE id=?",(profile or None,row['id']))
    raw = out / f"raw_{row['id']}.mp4"
    dest = out / f"clip_{row['id']}.mp4"
    tmp = out / f"clip_{row['id']}.partial.mp4"
    try:
        from banners import choose
        from source_media import cached_source,refine,prune_cache
        from filelock import FileLock
        cache=cache_root/'source-cache'
        cache.mkdir(parents=True,exist_ok=True)
        with FileLock(str(cache/(row['video_id']+'.lock')),timeout=1800):
            prune_cache(cache,exclude=row['video_id'])
            if row['video_id'].startswith('tg_'):
                from telegram_source import retrieve
                source=cache/(row['video_id']+'.mp4')
                # Recheck access and forwarding restrictions on each retrieval.
                retrieve(Path(db.execute('PRAGMA database_list').fetchone()[2]).resolve().parent,row['video_id'],row['url'],source)
            else: source=cached_source(row['url'],row['video_id'],cache)
            peak=row['peak'] if row['peak'] is not None else row['start']+(row['end']-row['start'])*.4
            if mode=='short':
                from source_media import probe
                a,b,method=0,probe(source),'whole'
                if not 5<=b<=61: raise ValueError('Downloaded source outside short duration range')
            else: a,b,method=refine(source,row['start'],row['end'],peak)
            if mode=='short':
                from duplicates import fingerprint,find_duplicate,store
                from source_media import stage
                stage('duplicate_check','Comparing source fingerprints')
                fp=fingerprint(source,b-a)
                with db:
                    store(db,row['id'],fp)
                    match=find_duplicate(db,row['id'],fp)
                    if match:
                        original,kind,similarity=match
                        db.execute("UPDATE clips SET status='duplicate',duplicate_of=?,duplicate_kind=?,updated=?,error=NULL WHERE id=?",(original,kind,int(time.time()),row['id']))
                if match:
                    stage('duplicate_check',f'#{row["id"]} matches #{original}: {kind}')
                    return True
            if mode=='short':
                from ad_filter import screen
                from source_media import stage
                stage('ad_check','Screening for third-party advertising')
                brandfile=Path(db.execute('PRAGMA database_list').fetchone()[2]).resolve().parent/'ad-brands.txt'
                brands=brandfile.read_text(encoding='utf-8').splitlines() if brandfile.is_file() else []
                try:
                    verdict,reason=screen(source,b-a,brands,reference_dir=brandfile.parent/'assets'/'ad-references')
                except Exception as exc:
                    verdict,reason='review',f'Screening incomplete: {str(exc)[:250]}'
                with db:
                    db.execute("UPDATE clips SET ad_result=? WHERE id=?",(reason,row['id']))
                    if verdict!='clean':
                        db.execute("UPDATE clips SET status=?,updated=?,error=NULL WHERE id=?",('ad_rejected' if verdict=='rejected' else 'ad_review',int(time.time()),row['id']))
                if verdict!='clean':
                    stage('ad_check',f'#{row["id"]}: {verdict} — {reason}')
                    return True
            selected=choose(campaigns,b-a,campaign=os.getenv('CLIP_CAMPAIGN_NAME') or None) if campaigns else banner
            if mode=='short':
                from short_media import render_short
                render_short(source,b,tmp,selected)
            else: render(source,a,b,tmp,selected)
        prune_cache(cache)
        print('CF_STAGE '+json.dumps({'stage':'save','detail':f'#{row["id"]}'},ensure_ascii=True),flush=True)
        tmp.replace(dest)
        cover=None
        cover_error=None
        if mode=='short' and os.getenv('CLIP_COVER_MODE','auto')!='off':
            try:
                from covers import generate
                from source_media import stage
                stage('cover','Generating cover')
                cover=str(generate(dest,dest.with_suffix('.jpg'),b-a,mode=os.getenv('CLIP_COVER_MODE','auto'),title=os.getenv('CLIP_COVER_TITLE',''),color=os.getenv('CLIP_COVER_COLOR','#172536')))
            except Exception as exc:
                cover_error=str(exc)[:500]
        with db:
            db.execute("UPDATE clips SET status='done',output=?,error=NULL,updated=?,campaign=?,actual_start=?,actual_end=?,boundary_method=?,cover=?,cover_error=? WHERE id=?", (str(dest),int(time.time()),getattr(selected,'name','manual') if selected else None,a,b,method,cover,cover_error,row['id']))
    except Exception as exc:
        print('CF_STAGE '+json.dumps({'stage':'error','detail':f'#{row["id"]}: {str(exc)[:300]}'},ensure_ascii=True),flush=True)
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
    sub.add_parser('scan').add_argument('--mode',choices=['long','short'],default='long')
    imp=sub.add_parser('import-short')
    imp.add_argument('video_id')
    tg=sub.add_parser('scan-telegram')
    tg.add_argument('channel')
    tg.add_argument('--limit',type=int,default=100)
    tg.add_argument('--min-views',type=int,default=0)
    library=sub.add_parser('scan-telegram-library')
    library.add_argument('--full',action='store_true')
    discovery=sub.add_parser('discover-telegram')
    discovery.add_argument('--query',action='append')
    sub.add_parser('status')
    sub.add_parser('retry')
    work=sub.add_parser('work')
    work.add_argument('--mode',choices=['long','short'],default='long')
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
    from filelock import FileLock, Timeout
    lock=FileLock(str(Path(args.db).resolve())+'.production.lock',timeout=0)
    try: lock.acquire()
    except Timeout: ap.error('Another production process is active')
    db=None
    try:
        db=connect(args.db)
        if args.action=='add': add_source(db,args.query)
        elif args.action=='import-short':
            result=inspect_video(db,{'id':args.video_id},dict(settings,min_views=0),mode='short')
            print('CF_STAGE '+json.dumps({'stage':'import_short','detail':result}),flush=True)
            if result!='ready': raise SystemExit(1)
            print('CF_PROGRESS 1 1',flush=True)
        elif args.action=='discover-telegram':
            from telegram_discovery import discover,QUERIES
            if discover(db,Path(args.db).resolve().parent,args.query or QUERIES): raise SystemExit(1)
        elif args.action=='scan-telegram-library':
            from telegram_source import scan_library
            if scan_library(db,Path(args.db).resolve().parent,args.full): raise SystemExit(1)
        elif args.action=='scan-telegram':
            from telegram_source import scan_channel
            print('CF_PROGRESS 0 1',flush=True)
            scan_channel(db,Path(args.db).resolve().parent,args.channel,args.limit,args.min_views)
            print('CF_PROGRESS 1 1',flush=True)
        elif args.action=='scan': print(json.dumps(scan(db,settings,mode=args.mode),ensure_ascii=False))
        elif args.action=='work':
            before_failed=db.execute("SELECT count(*) FROM clips WHERE status='failed'").fetchone()[0]
            total=min(args.limit,db.execute("SELECT count(*) FROM clips WHERE status='pending' AND mode=?",(args.mode,)).fetchone()[0])
            print(f'CF_PROGRESS 0 {total}',flush=True)
            for i in range(total):
                if not process(db,args.out,args.banner,args.campaigns,args.mode): break
                print(f'CF_PROGRESS {i+1} {total}',flush=True)
            failures=db.execute("SELECT count(*) FROM clips WHERE status='failed'").fetchone()[0]-before_failed
            print('CF_STAGE '+json.dumps({'stage':'batch_result','detail':f'{max(0,failures)} failed'},ensure_ascii=True),flush=True)
            if failures>0: raise SystemExit(1)
        elif args.action=='retry':
            with db:
                n=db.execute("UPDATE clips SET status='pending',updated=? WHERE status='failed' AND attempts<3",(int(time.time()),)).rowcount
            print('CF_STAGE '+json.dumps({'stage':'retry','detail':str(n)}),flush=True)
            print('CF_PROGRESS 1 1',flush=True)
        elif args.action=='status':
            for table in ('videos','clips'):
                print(table,dict(db.execute(f"SELECT status,COUNT(*) FROM {table} GROUP BY status").fetchall()))
    finally:
        if db is not None: db.close()
        lock.release()

if __name__=='__main__': main()
