"""Business account inventory over the existing publication tables."""
import csv
import io
import json
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PLATFORMS=('instagram','instagram_browser','telegram','youtube','tiktok','vk')
def init(db):
    from business_library import init as library_init
    library_init(db)
    db.execute("""CREATE TABLE IF NOT EXISTS business_accounts(
        account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
        timezone TEXT NOT NULL DEFAULT 'UTC',
        state TEXT NOT NULL DEFAULT 'new',
        avatar_id INTEGER REFERENCES business_materials(id),
        profile_id INTEGER REFERENCES business_materials(id),
        updated INTEGER NOT NULL)""")
    db.execute("INSERT OR IGNORE INTO business_accounts(account_id,updated) SELECT id,? FROM accounts",(int(time.time()),))

def import_csv(db,raw):
    from business_library import category
    if len(raw)>2*1024*1024: raise ValueError('CSV больше 2 МБ')
    try: source=raw.decode('utf-8-sig')
    except UnicodeError: raise ValueError('Используйте UTF-8')
    reader=csv.DictReader(io.StringIO(source,newline=''))
    required={'username','platform','category','timezone','daily_limit'}
    optional={'destination','token_env'}
    if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames) or not required.issubset(reader.fieldnames) or not set(reader.fieldnames)<=required|optional:
        raise ValueError('Некорректный заголовок CSV. Пароли и токены не импортируются.')
    items=[]
    for row in reader:
        n=reader.line_num
        if None in row or any(v is None for v in row.values()): raise ValueError(f'Строка {n}: неверное число полей')
        name=row['username'].strip().lstrip('@')
        platform=row['platform'].strip()
        dest=(row.get('destination') or name).strip()
        token=(row.get('token_env') or '').strip()
        if not name or len(name)>100 or platform not in PLATFORMS or len(dest)>200: raise ValueError(f'Строка {n}: неверный аккаунт')
        if platform=='instagram_browser':
            if not re.fullmatch(r'[A-Za-z0-9_.]{1,30}',name): raise ValueError(f'Строка {n}: неверный Instagram username')
            dest=name.lower(); token='LOCAL_BROWSER_SESSION'
        elif platform=='youtube':
            if not re.fullmatch(r'UC[A-Za-z0-9_-]{22}',dest): raise ValueError(f'Строка {n}: нужен YouTube channel ID')
            token='LOCAL_YOUTUBE_SESSION'
        elif not token: token='UNCONFIGURED_TOKEN'
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{2,80}',token): raise ValueError(f'Строка {n}: нужно имя переменной окружения')
        try:
            tz=ZoneInfo(row['timezone'].strip()).key
            daily=int(row['daily_limit'])
        except (ValueError,ZoneInfoNotFoundError): raise ValueError(f'Строка {n}: неверный часовой пояс или лимит')
        if not 1<=daily<=10: raise ValueError(f'Строка {n}: лимит 1–10')
        items.append((name,platform,dest,token,category(row['category']),daily,tz))
        if len(items)>5000: raise ValueError('Максимум 5000 строк')
    if not items: raise ValueError('CSV пуст')
    added=duplicates=0
    with db:
        db.execute('BEGIN IMMEDIATE')
        init(db)
        for name,platform,dest,token,topic,daily,tz in items:
            if db.execute('SELECT 1 FROM accounts WHERE name=? COLLATE NOCASE OR (platform=? AND destination=? COLLATE NOCASE)',(name,platform,dest)).fetchone():
                duplicates+=1; continue
            aid=db.execute('INSERT INTO accounts(name,platform,destination,token_env,topic,daily_limit,enabled) VALUES(?,?,?,?,?,?,0)',(name,platform,dest,token,topic,daily)).lastrowid
            db.execute('INSERT INTO business_accounts(account_id,timezone,updated) VALUES(?,?,?)',(aid,tz,int(time.time())))
            added+=1
    return added,duplicates

def assign(db,aid):
    """Reserve one avatar and profile together; no remote profile changes."""
    from business_library import category
    with db:
        db.execute('BEGIN IMMEDIATE')
        init(db)
        a=db.execute('SELECT a.topic,b.* FROM accounts a JOIN business_accounts b ON b.account_id=a.id WHERE a.id=?',(aid,)).fetchone()
        if not a: raise ValueError('Аккаунт не найден')
        if a['avatar_id'] or a['profile_id']: raise ValueError('Материалы уже назначены')
        ids=[]
        for kind in ('avatar','profile'):
            row=db.execute("SELECT id FROM business_materials WHERE kind=? AND status='free' AND category=? ORDER BY id LIMIT 1",(kind,category(a['topic']))).fetchone()
            if not row: raise ValueError('Нет свободных материалов нужной категории: '+kind)
            ids.append(row[0])
        now=int(time.time())
        db.executemany("UPDATE business_materials SET status='reserved',owner=?,updated=? WHERE id=?",[(f'account:{aid}',now,i) for i in ids])
        db.execute("UPDATE business_accounts SET avatar_id=?,profile_id=?,state='prepared',updated=? WHERE account_id=?",(*ids,now,aid))

def release(db,aid):
    with db:
        db.execute('BEGIN IMMEDIATE')
        init(db)
        a=db.execute('SELECT * FROM business_accounts WHERE account_id=?',(aid,)).fetchone()
        if not a: raise ValueError('Аккаунт не найден')
        now=int(time.time())
        db.execute("UPDATE business_materials SET status='free',owner=NULL,updated=? WHERE owner=? AND status='reserved' AND id IN (?,?)",(now,f'account:{aid}',a['avatar_id'],a['profile_id']))
        db.execute("UPDATE business_accounts SET avatar_id=NULL,profile_id=NULL,state='new',updated=? WHERE account_id=?",(now,aid))

def rows(db,limit=100,offset=0):
    init(db)
    return [dict(row) for row in db.execute("""SELECT a.id,a.name,a.platform,a.destination,a.token_env,a.topic,a.enabled,a.daily_limit,b.timezone,b.state,b.avatar_id,b.profile_id,m.payload profile_payload,
        (SELECT count(*) FROM publications p WHERE p.account_id=a.id AND p.status='sent') published,
        (SELECT count(*) FROM publications p WHERE p.account_id=a.id AND p.status IN ('blocked','browser_blocked','uncertain')) issues
        FROM accounts a JOIN business_accounts b ON b.account_id=a.id LEFT JOIN business_materials m ON m.id=b.profile_id ORDER BY a.id DESC LIMIT ? OFFSET ?""",(limit,offset))]
