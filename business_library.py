"""Local material inventory. No publication or account operations."""
import hashlib
import io
import json
import re
import time
from pathlib import Path

KINDS=('avatar','profile','caption')
def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS business_materials(
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, category TEXT NOT NULL,
        payload TEXT NOT NULL, digest TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'free',
        owner TEXT, created INTEGER NOT NULL, updated INTEGER NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS business_material_inventory ON business_materials(kind,category,status)")
def category(value):
    value=value.strip().casefold() or 'general'
    if len(value)>80 or any(ord(x)<32 for x in value): raise ValueError('Некорректная категория')
    return value
def parse(raw,kind):
    if kind not in ('profile','caption'): raise ValueError('Некорректный тип')
    if len(raw)>2*1024*1024: raise ValueError('TXT больше 2 МБ')
    try: text=raw.decode('utf-8-sig')
    except UnicodeError: raise ValueError('Сохраните TXT в UTF-8')
    tag=kind.upper()
    allowed={'name','category','bio'} if kind=='profile' else {'category','text','hashtags'}
    items=[]; current=None; key=None
    for n,line in enumerate(text.splitlines(),1):
        if line.strip()==f'[{tag}]':
            if current is not None: raise ValueError(f'Строка {n}: незакрытый блок')
            current={}; key=None
        elif line.strip()==f'[/{tag}]':
            if current is None: raise ValueError(f'Строка {n}: нет начала блока')
            required=('name','bio') if kind=='profile' else ('text',)
            if any(not current.get(k,'').strip() for k in required): raise ValueError(f'Строка {n}: отсутствует обязательное поле')
            current={k:v.strip() for k,v in current.items()}
            current['category']=category(current.get('category',''))
            if kind=='profile' and (len(current['name'])>64 or len(current['bio'])>150): raise ValueError(f'Строка {n}: имя до 64, BIO до 150 символов')
            if kind=='caption' and len(current['text']+' '+current.get('hashtags',''))>2200: raise ValueError(f'Строка {n}: описание до 2200 символов')
            items.append(current); current=None; key=None
        elif current is not None:
            match=re.match(r'^([a-z_]+)=(.*)$',line)
            if match:
                key,value=match.groups()
                if key not in allowed or key in current: raise ValueError(f'Строка {n}: неизвестное или повторное поле')
                current[key]=value
            elif key: current[key]+='\n'+line
            elif line.strip(): raise ValueError(f'Строка {n}: ожидается поле')
        elif line.strip(): raise ValueError(f'Строка {n}: ожидается [{tag}]')
    if current is not None: raise ValueError('Незакрытый блок в конце файла')
    if not 1<=len(items)<=5000: raise ValueError('Допустимо 1–5000 записей')
    return items
def insert(db,kind,cat,payload,digest=None):
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True)
    digest=digest or hashlib.sha256((kind+'\0'+encoded).encode()).hexdigest()
    now=int(time.time())
    return db.execute('INSERT OR IGNORE INTO business_materials(kind,category,payload,digest,created,updated) VALUES(?,?,?,?,?,?)',(kind,cat,encoded,digest,now,now)).rowcount
def import_text(db,raw,kind):
    items=parse(raw,kind)
    with db:
        init(db)
        added=sum(insert(db,kind,x['category'],x) for x in items)
    return added,len(items)-added
def import_images(db,root,files,cat):
    from PIL import Image,ImageOps
    cat=category(cat)
    if not 1<=len(files)<=100: raise ValueError('Выберите 1–100 изображений')
    prepared=[]
    for f in files:
        raw=f.stream.read(8*1024*1024+1)
        if len(raw)>8*1024*1024: raise ValueError('Изображение больше 8 МБ')
        try:
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in ('PNG','JPEG','WEBP') or im.width*im.height>16000000: raise ValueError('Недопустимое изображение')
                image=ImageOps.fit(ImageOps.exif_transpose(im).convert('RGB'),(512,512))
                buf=io.BytesIO(); image.save(buf,format='PNG'); content=buf.getvalue()
        except (OSError,Image.DecompressionBombError): raise ValueError('Не удалось открыть изображение')
        digest=hashlib.sha256(content).hexdigest()
        prepared.append((digest,content))
    folder=Path(root)/'assets'/'business-avatars'; folder.mkdir(parents=True,exist_ok=True)
    added=0
    with db:
        init(db)
        for digest,content in prepared:
            path=folder/(digest+'.png')
            if not path.exists(): path.write_bytes(content)
            added+=insert(db,'avatar',cat,{'file':path.name},'avatar:'+digest)
    return added,len(prepared)-added
def inventory(db):
    init(db)
    return {k:{s:n for s,n in db.execute('SELECT status,count(*) FROM business_materials WHERE kind=? GROUP BY status',(k,))} for k in KINDS}
def reserve(db,kind,cat,owner):
    if kind not in KINDS or not owner: raise ValueError('Некорректное резервирование')
    init(db)
    with db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT id FROM business_materials WHERE kind=? AND category=? AND status='free' ORDER BY id LIMIT 1",(kind,category(cat))).fetchone()
        if not row: return None
        db.execute("UPDATE business_materials SET status='reserved',owner=?,updated=? WHERE id=?",(owner,int(time.time()),row[0]))
        return row[0]
def finish(db,mid,owner,used=False):
    with db:
        return db.execute("UPDATE business_materials SET status=?,owner=?,updated=? WHERE id=? AND status='reserved' AND owner=?",('used' if used else 'free',owner if used else None,int(time.time()),mid,owner)).rowcount==1
def archive(db,mid,restore=False):
    with db:
        return db.execute('UPDATE business_materials SET status=?,updated=? WHERE id=? AND status=?',('free' if restore else 'archived',int(time.time()),mid,'archived' if restore else 'free')).rowcount==1
