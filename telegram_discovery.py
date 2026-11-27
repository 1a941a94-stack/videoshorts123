"""Discover public Telegram broadcast channels, without joining or posting."""
import time
from pathlib import Path
from filelock import FileLock
from source_media import stage
from telegram_source import client,channel_name,is_video_message

QUERIES=('видеомемы','мемы видео','смешные видео','приколы видео','угарные видео','мемы без текста','смешные животные','старые приколы','funny videos','video memes')

def qualifies(messages,min_videos=5,min_fraction=.2):
    total=videos=0
    for msg in messages:
        if getattr(msg,'action',None): continue
        total+=1
        if not is_video_message(msg) or getattr(msg,'noforwards',False): continue
        file=msg.file
        if file and 5<=(file.duration or 0)<=60 and 0<(file.size or 0)<=100*1024**2:
            videos+=1
    return total,videos,total>0 and videos>=min_videos and videos/total>=min_fraction

def discover(db,root,queries=QUERIES,limit=15,sample=30):
    from telethon.tl.functions.contacts import SearchRequest
    from telethon.tl.types import Channel
    from telethon.errors import FloodWaitError,RPCError
    if not 1<=limit<=30 or not 10<=sample<=50: raise ValueError('Invalid discovery limits')
    queries=list(dict.fromkeys(q.strip() for q in queries if q.strip()))
    if not queries or len(queries)>20 or any(len(q)>100 for q in queries): raise ValueError('Invalid search queries')
    seen=set()
    added=0
    failures=0
    with FileLock(str(Path(root)/'telegram-reader.lock'),timeout=0):
        c=client(root)
        try:
            c.connect()
            if not c.is_user_authorized(): raise RuntimeError('Run Telegram login first')
            print(f'CF_PROGRESS 0 {len(queries)}',flush=True)
            for i,q in enumerate(queries,1):
                stage('telegram_discover',q)
                result=c(SearchRequest(q=q,limit=limit))
                for entity in result.chats:
                    if not isinstance(entity,Channel) or not entity.broadcast or not entity.username or getattr(entity,'noforwards',False): continue
                    if entity.id in seen: continue
                    seen.add(entity.id)
                    if len(seen)>100: break
                    name=channel_name(entity.username)
                    if db.execute('SELECT 1 FROM telegram_channels WHERE name=?',(name,)).fetchone(): continue
                    try:
                        total,videos,ok=qualifies(c.iter_messages(entity,limit=sample))
                    except FloodWaitError: raise
                    except RPCError:
                        failures+=1
                        continue
                    if ok:
                        with db:
                            cur=db.execute("INSERT OR IGNORE INTO telegram_channels(name,history,min_views) VALUES(?,100,0)",(name,))
                            added+=cur.rowcount
                        stage('telegram_discover',f'@{name}: {videos}/{total} eligible videos')
                    time.sleep(2)
                print(f'CF_PROGRESS {i} {len(queries)}',flush=True)
                if len(seen)>100: break
                if i<len(queries): time.sleep(3)
            stage('telegram_discover',f'Added {added}; checked {min(len(seen),100)}; inaccessible {failures}')
            return 0
        except FloodWaitError as exc:
            stage('error',f'Telegram rate limit: {exc.seconds}s; stopped')
            return 1
        finally: c.disconnect()
