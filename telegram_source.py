"""Telegram source adapter for channels accessible to the signed-in account."""
import os
import re
import time
import math
from pathlib import Path
from source_media import stage,probe
from filelock import FileLock

def channel_name(value):
    value=value.strip().removeprefix('https://t.me/').removeprefix('@').rstrip('/')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}',value):
        raise ValueError('Enter a public channel username or t.me link')
    return value.lower()

def client(root):
    from telethon.sync import TelegramClient
    api_id=int(os.environ['TG_API_ID'])
    api_hash=os.environ['TG_API_HASH']
    return TelegramClient(str(Path(root).resolve()/'telegram-reader'),api_id,api_hash,
                          request_retries=2,connection_retries=2,flood_sleep_threshold=0)

def login(root):
    with FileLock(str(Path(root)/'telegram-reader.lock'),timeout=0):
        c=client(root)
        try: c.start()
        finally: c.disconnect()

def scan_channel(db,root,channel,limit=100,min_views=1000):
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
            for i,msg in enumerate(c.iter_messages(entity,limit=limit),1):
                if i%10==0: stage('telegram_scan',f'@{channel}: {i}/{limit}')
                if not msg.video or getattr(msg,'noforwards',False): continue
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
                        (vid,duration,clips[0]['score'],clips[0]['rank'],now))
                    count+=row.rowcount
            stage('telegram_scan',f'New candidates: {count}')
            return count
        finally: c.disconnect()

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
            if not msg or not msg.video or getattr(msg,'noforwards',False): raise ValueError('Video unavailable or restricted')
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
