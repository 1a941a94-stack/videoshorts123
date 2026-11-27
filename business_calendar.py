"""Editorial calendar; creates drafts only, never sends or approves them."""
import json
import time
from datetime import datetime, timezone, timedelta

def init(db):
    from business_library import init as library_init
    library_init(db)
    db.execute("""CREATE TABLE IF NOT EXISTS calendar_materials(
        publication_id INTEGER PRIMARY KEY REFERENCES publications(id),
        material_id INTEGER NOT NULL REFERENCES business_materials(id))""")

def parse_date(value):
    try: return int(datetime.strptime(value,'%Y-%m-%dT%H:%M').replace(tzinfo=timezone.utc).timestamp())
    except ValueError: raise ValueError('Укажите дату и время UTC')

def create_draft(db,aid,cid,mid,scheduled,caption):
    from business_library import category
    now=int(time.time())
    if scheduled<now: raise ValueError('Выберите будущее время')
    with db:
        db.execute('BEGIN IMMEDIATE')
        init(db)
        a=db.execute('SELECT * FROM accounts WHERE id=?',(aid,)).fetchone()
        c=db.execute("SELECT * FROM clips WHERE id=? AND status='done' AND output IS NOT NULL",(cid,)).fetchone()
        if not a or not c: raise ValueError('Аккаунт или готовый ролик не найден')
        if a['production_profile'] and a['production_profile']!=c['production_profile']: raise ValueError('Ролик не соответствует профилю монтажа')
        if db.execute('SELECT 1 FROM publications WHERE account_id=? AND clip_id=?',(aid,cid)).fetchone(): raise ValueError('Ролик уже назначен этому аккаунту')
        if mid:
            m=db.execute("SELECT * FROM business_materials WHERE id=? AND kind='caption' AND status='free'",(mid,)).fetchone()
            if not m or m['category'] not in (category(a['topic']),'general'): raise ValueError('Описание недоступно или не соответствует категории')
            p=json.loads(m['payload'])
            caption=(p['text']+' '+p.get('hashtags','')).strip()
        if len(caption)>1024: raise ValueError('Описание должно быть не длиннее 1024 символов')
        pid=db.execute("INSERT INTO publications(account_id,clip_id,caption,scheduled,updated,status) VALUES(?,?,?,?,?,'draft')",(aid,cid,caption,scheduled,now)).lastrowid
        if mid:
            db.execute("UPDATE business_materials SET status='reserved',owner=?,updated=? WHERE id=?",(f'publication:{pid}',now,mid))
            db.execute('INSERT INTO calendar_materials VALUES(?,?)',(pid,mid))
        return pid

def modify(db,pid,operation,scheduled=None):
    now=int(time.time())
    with db:
        db.execute('BEGIN IMMEDIATE')
        init(db)
        row=db.execute('SELECT status FROM publications WHERE id=?',(pid,)).fetchone()
        if not row or row['status'] not in ('draft','approved'): raise ValueError('Можно изменить только неотправленные задачи')
        if operation=='move':
            if scheduled is None or scheduled<now: raise ValueError('Выберите будущее время')
            db.execute("UPDATE publications SET scheduled=?,updated=?,status='draft' WHERE id=?",(scheduled,now,pid))
        elif operation=='cancel':
            db.execute("UPDATE publications SET status='cancelled',updated=? WHERE id=?",(now,pid))
            db.execute("UPDATE business_materials SET status='free',owner=NULL,updated=? WHERE status='reserved' AND owner=? AND id IN (SELECT material_id FROM calendar_materials WHERE publication_id=?)",(now,f'publication:{pid}',pid))
        else: raise ValueError('Неизвестная операция')

def reconcile(db):
    """Record material use only after confirmed delivery; uncertain retains reservation."""
    init(db)
    db.execute("""UPDATE business_materials SET status='used',updated=?
        WHERE status='reserved' AND EXISTS(SELECT 1 FROM calendar_materials cm JOIN publications p ON p.id=cm.publication_id
        WHERE cm.material_id=business_materials.id AND business_materials.owner='publication:'||p.id
        AND p.status IN ('sent','uploaded_private'))""",(int(time.time()),))

def overview(db):
    now=int(time.time())
    return dict(next=[dict(x) for x in db.execute("""SELECT p.id,p.scheduled,p.status,a.name FROM publications p JOIN accounts a ON a.id=p.account_id
        WHERE p.status IN ('draft','approved') ORDER BY p.scheduled LIMIT 5""")],
        counts=dict(db.execute('SELECT status,count(*) FROM publications GROUP BY status')))

def calendar(db,days,aid=None):
    init(db)
    reconcile(db)
    start=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    end=start+timedelta(days=days)
    where='p.scheduled>=? AND p.scheduled<?'; args=[int(start.timestamp()),int(end.timestamp())]
    if aid: where+=' AND p.account_id=?'; args.append(aid)
    rows=[dict(x) for x in db.execute('SELECT p.id,p.clip_id,p.caption,p.scheduled,p.status,a.name,a.platform FROM publications p JOIN accounts a ON a.id=p.account_id WHERE '+where+' ORDER BY p.scheduled,p.id LIMIT 1000',args)]
    for row in rows:
        dt=datetime.fromtimestamp(row['scheduled'],timezone.utc)
        row['date']=dt.strftime('%Y-%m-%d %H:%M')
        row['input_date']=dt.strftime('%Y-%m-%dT%H:%M')
    return dict(rows=rows,accounts=[dict(x) for x in db.execute('SELECT id,name,topic FROM accounts ORDER BY name')],clips=[dict(x) for x in db.execute("SELECT id,production_profile FROM clips WHERE status='done' AND output IS NOT NULL ORDER BY id DESC LIMIT 200")],captions=[{**dict(x),'payload':json.loads(x['payload'])} for x in db.execute("SELECT id,category,payload FROM business_materials WHERE kind='caption' AND status='free' ORDER BY id LIMIT 200")],summary=overview(db))
