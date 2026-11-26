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
    return db

def add_account(db,name,platform,destination,token_env,topic='',daily_limit=2,interval_seconds=3600):
    if platform not in ('telegram','youtube','instagram','tiktok','vk'): raise ValueError('Unknown platform')
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

def approve(db,pid):
    with db:
        return db.execute("UPDATE publications SET status='approved',updated=? WHERE id=? AND status='draft'",(int(time.time()),pid)).rowcount==1

def claim(db,now):
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute("""SELECT p.*,a.platform,a.destination,a.token_env,c.output FROM publications p
        JOIN accounts a ON a.id=p.account_id JOIN clips c ON c.id=p.clip_id
        WHERE p.status='approved' AND a.enabled=1 AND p.scheduled<=? AND c.status='done'
        AND a.platform='telegram'
        AND NOT EXISTS(SELECT 1 FROM publications q WHERE q.account_id=a.id AND q.status IN ('sending','uncertain'))
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

def send_one(db,root,sender=telegram):
    row=claim(db,int(time.time()))
    if not row: return False
    try:
        path=(root/row['output']).resolve()
        token=os.environ.get(row['token_env'])
        if not token or not path.is_relative_to((root/'output').resolve()) or not path.is_file():
            with db: db.execute("UPDATE publications SET status='blocked',error='Missing credential or output',updated=? WHERE id=?",(int(time.time()),row['id']))
            return True
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
        elif args.action=='send':
            with FileLock(str(root/'publication.lock'),timeout=0):
                with db: db.execute("UPDATE publications SET status='uncertain',error='Interrupted upload; reconcile manually' WHERE status='sending'")
                while send_one(db,root): pass
        elif args.action=='measure': measure(db,args.id,args.views,args.accepted,args.kopecks)
        else:
            for table in ('accounts','publications','measurements'):
                print(table,json.dumps([dict(r) for r in db.execute('SELECT * FROM '+table)],ensure_ascii=False))
    finally: db.close()
if __name__=='__main__': main()
