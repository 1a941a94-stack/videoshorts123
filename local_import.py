"""Import user-provided media into the ordinary short production queue."""
import hashlib
import math
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from quality import inspect

EXTENSIONS={'.mp4','.mov','.webm','.mkv'}
MAX_BYTES=256*1024**2

def import_file(db,root,source,title=None):
    source=Path(source)
    if source.suffix.lower() not in EXTENSIONS: raise ValueError('Unsupported video extension')
    if not 0<source.stat().st_size<=MAX_BYTES: raise ValueError('File exceeds 256 MiB or is empty')
    folder=Path(root).resolve()/'local-sources'
    folder.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=folder,suffix=source.suffix.lower(),delete=False) as fp:
            temp=Path(fp.name)
            digest=hashlib.sha256()
            size=0
            with source.open('rb') as inp:
                for block in iter(lambda:inp.read(1024*1024),b''):
                    size+=len(block)
                    if size>MAX_BYTES: raise ValueError('File exceeds limit')
                    digest.update(block)
                    fp.write(block)
        vid='local_'+digest.hexdigest()
        data=inspect(temp)
        duration=float(data['format']['duration'])
        video=next((s for s in data['streams'] if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')),None)
        if not video or not math.isfinite(duration) or not 5<=duration<=60: raise ValueError('Expected video of 5–60 seconds')
        if not 16<=min(video['width'],video['height'])<=max(video['width'],video['height'])<=4096: raise ValueError('Invalid source dimensions')
        target=folder/(vid+source.suffix.lower())
        now=int(time.time())
        db.execute('BEGIN IMMEDIATE')
        with db:
            existing=db.execute('SELECT url FROM videos WHERE id=?',(vid,)).fetchone()
            if existing:
                name=existing['url'].removeprefix('local:')
                if name==vid+Path(name).suffix and Path(name).suffix in EXTENSIONS:
                    previous=folder/name
                    if not previous.exists(): os.replace(temp,previous)
                return 'duplicate'
            os.replace(temp,target)
            db.execute("INSERT INTO videos(id,url,title,views,duration,status,checked) VALUES (?,?,?,?,?,'ready',?)",(vid,'local:'+target.name,(title or source.name)[:200],0,duration,now))
            db.execute("INSERT INTO clips(video_id,start,end,score,rank,mode,status,updated) VALUES (?,0,?,0.5,0.5,'short','pending',?)",(vid,duration,now))
        return 'ready'
    finally:
        if temp: temp.unlink(missing_ok=True)

def resolve_source(root,vid,url):
    if not re.fullmatch(r'local_[a-f0-9]{64}',vid): raise ValueError('Invalid local ID')
    name=url.removeprefix('local:')
    if not url.startswith('local:') or name!=vid+Path(name).suffix or Path(name).suffix not in EXTENSIONS: raise ValueError('Invalid local source')
    folder=(Path(root)/'local-sources').resolve()
    path=(folder/name).resolve()
    if not path.is_relative_to(folder) or not path.is_file(): raise ValueError('Local source missing')
    return path

def import_folder(db,root,folder):
    paths=sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)
    if len(paths)>1000: raise ValueError('Maximum 1000 files per batch')
    results=[]
    for path in paths:
        try: results.append((path.name,import_file(db,root,path)))
        except Exception as exc: results.append((path.name,'error: '+str(exc)[:200]))
    return results
