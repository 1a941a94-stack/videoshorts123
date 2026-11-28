"""Telegram source adapter for channels accessible to the signed-in account."""
import os
import re
import time
import math
from pathlib import Path
from source_media import stage,probe
from filelock import FileLock

def is_video_message(msg):
    if not msg or not getattr(msg,'video',None) or getattr(msg,'gif',None): return False
    doc=getattr(msg,'document',None)
    if getattr(doc,'mime_type','')=='image/gif': return False
    from telethon.tl.types import DocumentAttributeAnimated
    return not any(isinstance(a,DocumentAttributeAnimated) for a in getattr(doc,'attributes',[]))

def channel_name(value):
    value=value.strip().removeprefix('https://t.me/').removeprefix('@').rstrip('/')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}',value):
        raise ValueError('Enter a public channel username or t.me link')
    return value.lower()

def credentials():
    api_id=os.getenv('TG_API_ID','').strip()
    api_hash=os.getenv('TG_API_HASH','').strip()
    if not api_id.isdigit() or int(api_id)<=0 or not re.fullmatch(r'[a-fA-F0-9]{32}',api_hash):
        raise ValueError('Telegram: задайте TG_API_ID и TG_API_HASH в PowerShell перед запуском программы, затем выполните telegram_source.py login.')
    return int(api_id),api_hash

def client(root):
    from telegram_proxy import connection_options
    api_id,api_hash=credentials()
    from telethon.sync import TelegramClient
    return TelegramClient(str(Path(root).resolve()/'telegram-reader'),api_id,api_hash,
                          request_retries=2,connection_retries=2,flood_sleep_threshold=0,**connection_options(root))

def login(root):
    with FileLock(str(Path(root)/'telegram-reader.lock'),timeout=0):
        c=client(root)
        try: c.start()
        finally: c.disconnect()

def scan_channel(db,root,channel,limit=100,min_views=0,cursor=None):
    from short_media import candidate
    channel=channel_name(channel)
    if not 1<=limit<=1000: raise ValueError('Invalid history limit')
    with FileLock(str(Path(root)/'telegram-reader.lock'),timeout=0):
        c=client(root)
        try:
            c.connect()
            if not c.is_user_authorized(): raise RuntimeError('Run Telegram login first')
            entity=c.get_entity(channel)
            if getattr(entity,'noforwards',False): raise ValueError('Channel restricts saving or forwarding')
            count=0
            newest=cursor or 0
            # First scan recent history; subsequent scans oldest-first to avoid gaps.
            opts={'limit':limit} if cursor is None else {'limit':limit,'min_id':cursor,'reverse':True}
            for i,msg in enumerate(c.iter_messages(entity,**opts),1):
                newest=max(newest,msg.id)
                if i%10==0: stage('telegram_scan',f'@{channel}: {i}/{limit}')
                if not is_video_message(msg) or getattr(msg,'noforwards',False): continue
                duration=getattr(msg.file,'duration',0) or 0
                views=msg.views or 0
                clips=candidate({'duration':duration,'view_count':views},min_views)
                if not clips or (msg.file.size or 0)>100*1024**2: continue
                vid=f'tg_{entity.id}_{msg.id}'
                url=f'https://t.me/{channel}/{msg.id}'
                now=int(time.time())
                with db:
                    db.execute("INSERT OR IGNORE INTO videos(id,url,title,views,duration,status,checked) VALUES(?,?,?,?,?,'ready',?)",
                        (vid,url,(msg.message or f'@{channel} #{msg.id}')[:200],views,duration,now))
                    row=db.execute("INSERT OR IGNORE INTO clips(video_id,start,end,score,rank,updated,mode) VALUES(?,0,?,?,?,?,'short')",
                        (vid,duration,clips[0]['score'],0.5,now))
                    count+=row.rowcount
            stage('telegram_scan',f'New candidates: {count}')
            return count,newest
        finally: c.disconnect()

def add_channels(db,values,limit=100,min_views=0):
    if not 1<=limit<=1000 or min_views<0: raise ValueError('Invalid settings')
    names=list(dict.fromkeys(channel_name(v) for v in values if v.strip()))
    if not names or len(names)>200: raise ValueError('Provide 1–200 channels')
    with db:
        for name in names:
            db.execute("INSERT OR IGNORE INTO telegram_channels(name,history,min_views) VALUES(?,?,?)",(name,limit,min_views))
    return len(names)

def scan_library(db,root,full=False,*,approved_only=False):
    from telethon.errors import FloodWaitError
    rows=db.execute("SELECT * FROM telegram_channels WHERE enabled=1"+(" AND auto_allowed=1 AND coalesce(last_scan,0)<=?" if approved_only else "")+" ORDER BY coalesce(last_scan,0),name"+(" LIMIT 3" if approved_only else ""), (int(time.time())-3600,) if approved_only else ()).fetchall()
    failures=0
    try: credentials()
    except ValueError as exc:
        stage('error',str(exc))
        print(str(exc),flush=True)
        return 1
    print(f'CF_PROGRESS 0 {len(rows)}',flush=True)
    for i,row in enumerate(rows,1):
        name=row['name']
        try:
            stage('telegram_scan',f'@{name} · {i}/{len(rows)}')
            count,newest=scan_channel(db,root,name,min(row['history'],30) if approved_only else row['history'],row['min_views'],None if full else row['cursor'])
            with db:
                db.execute("UPDATE telegram_channels SET cursor=max(coalesce(cursor,0),?),last_scan=?,found=found+?,error=NULL WHERE name=?",(newest,int(time.time()),count,name))
        except FloodWaitError as exc:
            with db: db.execute("UPDATE telegram_channels SET error=?,last_scan=? WHERE name=?",(f'Telegram rate limit: {exc.seconds}s',int(time.time())+max(0,exc.seconds-3600),name))
            stage('error',f'Telegram rate limit: {exc.seconds}s; stopped')
            return 1
        except Exception as exc:
            failures+=1
            with db: db.execute("UPDATE telegram_channels SET error=?,last_scan=? WHERE name=?",(str(exc)[:300],int(time.time()),name))
            stage('error',f'@{name}: {type(exc).__name__}: {str(exc)[:240]}')
            print(f'@{name}: {type(exc).__name__}: {str(exc)[:240]}',flush=True)
        print(f'CF_PROGRESS {i} {len(rows)}',flush=True)
        if i<len(rows): time.sleep(2)
    return failures

def retrieve(root,vid,url,target):
    from urllib.parse import urlsplit
    import tempfile
    match=re.fullmatch(r'tg_(\d+)_(\d+)',vid)
    u=urlsplit(url)
    parts=u.path.strip('/').split('/')
    if not match or u.scheme!='https' or u.hostname!='t.me' or len(parts)!=2 or parts[1]!=match[2]:
        raise ValueError('Invalid Telegram source')
    with FileLock(str(Path(root)/'telegram-reader.lock'),timeout=30):
        c=client(root)
        try:
            c.connect()
            if not c.is_user_authorized(): raise RuntimeError('Run Telegram login first')
            entity=c.get_entity(channel_name(parts[0]))
            if str(entity.id)!=match[1] or getattr(entity,'noforwards',False): raise ValueError('Source changed or restricts saving')
            msg=c.get_messages(entity,ids=int(match[2]))
            if not is_video_message(msg) or getattr(msg,'noforwards',False): raise ValueError('Video unavailable, animated GIF, or restricted')
            if (msg.file.size or 0)>100*1024**2: raise ValueError('Video exceeds size limit')
            stage('download','Telegram')
            with tempfile.TemporaryDirectory(dir=Path(target).parent) as folder:
                path=c.download_media(msg,file=str(Path(folder)/'video.mp4'))
                if not path or not 5<=probe(path)<=61: raise ValueError('Invalid short video duration')
                Path(path).replace(target)
        finally: c.disconnect()

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['login'])
    p.parse_args()
    login(Path(__file__).resolve().parent)
