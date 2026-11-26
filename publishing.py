"""Explicitly approved publication queue; credentials are kept in environment variables."""
import argparse, os, re, time, json
from pathlib import Path
from pipeline import connect
from filelock import FileLock

def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS accounts(
      id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, platform TEXT NOT NULL,
      destination TEXT NOT NULL, token_env TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '',
      daily_limit INTEGER NOT NULL DEFAULT 2, interval_seconds INTEGER NOT NULL DEFAULT 3600,
      enabled INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS publications(
      id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
      clip_id INTEGER NOT NULL REFERENCES clips(id), caption TEXT NOT NULL,
      scheduled INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
      updated INTEGER NOT NULL, remote_id TEXT, url TEXT, error TEXT,
      UNIQUE(account_id,clip_id));
    CREATE TABLE IF NOT EXISTS measurements(
      publication_id INTEGER PRIMARY KEY REFERENCES publications(id),
      views INTEGER NOT NULL DEFAULT 0, accepted_views INTEGER NOT NULL DEFAULT 0,
      revenue_kopecks INTEGER NOT NULL DEFAULT 0, measured INTEGER NOT NULL);
    """)
    db.execute('BEGIN IMMEDIATE')
    with db:
        cols={r[1] for r in db.execute('PRAGMA table_info(accounts)')}
        for name,kind in [('production_profile','TEXT'),('auto_queue','INTEGER NOT NULL DEFAULT 0'),('caption_template',"TEXT NOT NULL DEFAULT ''")]:
            if name not in cols: db.execute(f'ALTER TABLE accounts ADD COLUMN {name} {kind}')
    return db

def add_account(db,name,platform,destination,token_env,topic='',daily_limit=2,interval_seconds=3600):
    if platform not in ('telegram','youtube','instagram','instagram_browser','tiktok','vk'): raise ValueError('Unknown platform')
    if platform=='instagram_browser':
        from instagram_browser import username
        destination=username(destination)
        token_env='LOCAL_BROWSER_SESSION'
    if not re.fullmatch(r'[A-Z][A-Z0-9_]{2,80}',token_env): raise ValueError('Expected environment variable name, not token')
    if not name.strip() or not destination.strip() or not 1<=daily_limit<=10 or interval_seconds<60: raise ValueError('Invalid account settings')
    with db:
        db.execute('INSERT INTO accounts(name,platform,destination,token_env,topic,daily_limit,interval_seconds) VALUES (?,?,?,?,?,?,?)',
                   (name,platform,destination,token_env,topic,daily_limit,interval_seconds))

def enqueue(db,account,clip,caption,scheduled):
    row=db.execute("SELECT status FROM clips WHERE id=?",(clip,)).fetchone()
    if not row or row['status']!='done': raise ValueError('Clip is not ready')
    with db:
        db.execute("INSERT OR IGNORE INTO publications(account_id,clip_id,caption,scheduled,updated) VALUES(?,?,?,?,?)",(account,clip,caption,scheduled,int(time.time())))

def sync_ready(db,now=None):
    """Queue only explicitly opted-in accounts, matching their production profile."""
    now=int(time.time()) if now is None else int(now)
    count=0
    db.execute('BEGIN IMMEDIATE')
    with db:
        accounts=db.execute("SELECT * FROM accounts WHERE enabled=1 AND auto_queue=1 AND platform IN ('telegram','instagram','instagram_browser') AND production_profile IS NOT NULL").fetchall()
        for a in accounts:
            last=db.execute("SELECT max(scheduled) FROM publications WHERE account_id=? AND status IN ('approved','sending','sent','uncertain')",(a['id'],)).fetchone()[0]
            slot=max(now,(last or 0)+a['interval_seconds'])
            rows=db.execute("""SELECT c.id FROM clips c WHERE c.status='done' AND c.production_profile=?
                AND NOT EXISTS(SELECT 1 FROM publications p WHERE p.account_id=? AND p.clip_id=c.id)
                ORDER BY c.id LIMIT 1000""",(a['production_profile'],a['id'])).fetchall()
            for row in rows:
                caption=a['caption_template'] or ''
                cur=db.execute("INSERT OR IGNORE INTO publications(account_id,clip_id,caption,scheduled,updated,status) VALUES(?,?,?,?,?,'approved')",(a['id'],row['id'],caption,slot,now))
                if cur.rowcount: count+=1; slot+=a['interval_seconds']
    return count

def configure_auto(db,account,profile,caption,interval,enabled):
    if not 60<=interval<=86400 or len(caption)>1024: raise ValueError('Invalid posting settings')
    if enabled and not profile: raise ValueError('Choose a production profile')
    with db:
        row=db.execute('SELECT platform FROM accounts WHERE id=?',(account,)).fetchone()
        if not row or (enabled and row['platform'] not in ('telegram','instagram','instagram_browser')): raise ValueError('Unsupported automatic publication platform')
        db.execute('UPDATE accounts SET production_profile=?,caption_template=?,interval_seconds=?,auto_queue=? WHERE id=?',(profile or None,caption,interval,int(enabled),account))

def approve(db,pid):
    with db:
        return db.execute("UPDATE publications SET status='approved',updated=? WHERE id=? AND status='draft'",(int(time.time()),pid)).rowcount==1

def claim(db,now):
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute("""SELECT p.*,a.platform,a.destination,a.token_env,c.output FROM publications p
        JOIN accounts a ON a.id=p.account_id JOIN clips c ON c.id=p.clip_id
        WHERE p.status='approved' AND a.enabled=1 AND p.scheduled<=? AND c.status='done'
        AND a.platform IN ('telegram','instagram','instagram_browser')
        AND NOT EXISTS(SELECT 1 FROM publications q WHERE q.account_id=a.id AND q.status IN ('sending','uncertain','browser_blocked','blocked'))
        AND (SELECT count(*) FROM publications q WHERE q.account_id=a.id AND q.status='sent' AND q.updated>?)<a.daily_limit
        AND NOT EXISTS(SELECT 1 FROM publications q WHERE q.account_id=a.id AND q.status='sent' AND q.updated>?-a.interval_seconds)
        ORDER BY p.scheduled,p.id LIMIT 1""",(now,now-86400,now)).fetchone()
        if row: db.execute("UPDATE publications SET status='sending',updated=? WHERE id=?",(now,row['id']))
        db.commit()
        return row
    except BaseException:
        db.rollback()
        raise

def telegram(row,path,token):
    import requests
    if len(row['caption'])>1024: raise ValueError('Telegram caption exceeds limit')
    with path.open('rb') as fp:
        response=requests.post('https://api.telegram.org/bot'+token+'/sendVideo',
            data={'chat_id':row['destination'],'caption':row['caption'],'supports_streaming':'true'},
            files={'video':(path.name,fp,'video/mp4')},timeout=(15,180))
    data=response.json()
    if not response.ok or not data.get('ok'): raise RuntimeError('Telegram rejected upload')
    result=data['result']
    chat=result['chat']
    link=('https://t.me/'+chat['username']+'/'+str(result['message_id'])) if chat.get('username') else None
    return str(result['message_id']),link

def send_one(db,root,sender=None):
    row=claim(db,int(time.time()))
    if not row: return False
    try:
        path=(root/row['output']).resolve()
        token=os.environ.get(row['token_env'])
        if (not token and row['platform']!='instagram_browser') or not path.is_relative_to((root/'output').resolve()) or not path.is_file():
            with db: db.execute("UPDATE publications SET status='blocked',error='Missing credential or output',updated=? WHERE id=?",(int(time.time()),row['id']))
            return True
        if sender is None and row['platform']=='instagram_browser':
            from instagram_browser import publish,BrowserBlocked
            try: remote,link=publish(root,row,path)
            except BrowserBlocked as exc:
                with db: db.execute("UPDATE publications SET status='browser_blocked',error=?,updated=? WHERE id=?",(str(exc),int(time.time()),row['id']))
                return True
        else:
            if sender is None:
                if row['platform']=='instagram':
                    from instagram_publish import publish as sender
                else: sender=telegram
            remote,link=sender(row,path,token)
        with db: db.execute("UPDATE publications SET status='sent',remote_id=?,url=?,updated=?,error=NULL WHERE id=?",(remote,link,int(time.time()),row['id']))
    except Exception:
        # A network failure may occur after remote acceptance: never blindly resend.
        with db: db.execute("UPDATE publications SET status='uncertain',error='Upload outcome needs manual reconciliation',updated=? WHERE id=?",(int(time.time()),row['id']))
    return True

def measure(db,pid,views,accepted,revenue):
    if not 0<=accepted<=views or revenue<0: raise ValueError('Invalid measurement')
    if not db.execute("SELECT 1 FROM publications WHERE id=? AND status='sent'",(pid,)).fetchone(): raise ValueError('Not published')
    with db: db.execute("INSERT INTO measurements VALUES(?,?,?,?,?) ON CONFLICT(publication_id) DO UPDATE SET views=excluded.views,accepted_views=excluded.accepted_views,revenue_kopecks=excluded.revenue_kopecks,measured=excluded.measured",(pid,views,accepted,revenue,int(time.time())))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path('.'))
    sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('account'); a.add_argument('name'); a.add_argument('platform'); a.add_argument('destination'); a.add_argument('token_env'); a.add_argument('--topic',default=''); a.add_argument('--daily',type=int,default=2)
    a=sub.add_parser('enable'); a.add_argument('id',type=int); a.add_argument('--off',action='store_true')
    a=sub.add_parser('draft'); a.add_argument('account',type=int); a.add_argument('clip',type=int); a.add_argument('caption'); a.add_argument('--scheduled',type=int,default=0)
    a=sub.add_parser('approve'); a.add_argument('id',type=int)
    sub.add_parser('send')
    sub.add_parser('stop')
    sub.add_parser('sync')
    sub.add_parser('run')
    sub.add_parser('status')
    a=sub.add_parser('measure'); a.add_argument('id',type=int); a.add_argument('views',type=int); a.add_argument('accepted',type=int); a.add_argument('kopecks',type=int)
    args=p.parse_args(); root=args.root.resolve()
    db=init(connect(root/'clipfactory.sqlite3'))
    try:
        if args.action=='account': add_account(db,args.name,args.platform,args.destination,args.token_env,args.topic,args.daily)
        elif args.action=='enable':
            with db: db.execute('UPDATE accounts SET enabled=? WHERE id=?',(int(not args.off),args.id))
        elif args.action=='draft': enqueue(db,args.account,args.clip,args.caption,args.scheduled or int(time.time()))
        elif args.action=='approve': print(approve(db,args.id))
        elif args.action=='stop': (root/'publication.stop').touch()
        elif args.action=='sync': print(sync_ready(db))
        elif args.action in ('send','run'):
            with FileLock(str(root/'publication.lock'),timeout=0):
                with db: db.execute("UPDATE publications SET status='uncertain',error='Interrupted upload; reconcile manually' WHERE status='sending'")
                stop=root/'publication.stop'
                if args.action=='run': stop.unlink(missing_ok=True)
                while not stop.exists():
                    if args.action=='run': sync_ready(db)
                    while not stop.exists() and send_one(db,root): pass
                    if args.action=='send': break
                    for _ in range(30):
                        if stop.exists(): break
                        time.sleep(1)
        elif args.action=='measure': measure(db,args.id,args.views,args.accepted,args.kopecks)
        else:
            for table in ('accounts','publications','measurements'):
                print(table,json.dumps([dict(r) for r in db.execute('SELECT * FROM '+table)],ensure_ascii=False))
    finally: db.close()
if __name__=='__main__': main()
