"""Inventory of infrastructure services and recorded expenses, without purchasing or routing traffic."""
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

KINDS=('network','hosting','storage','api','other')
def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS business_services(
        id INTEGER PRIMARY KEY, supplier TEXT NOT NULL, name TEXT NOT NULL,
        kind TEXT NOT NULL, expires INTEGER, status TEXT NOT NULL DEFAULT 'active',
        created INTEGER NOT NULL, UNIQUE(supplier,name))""")
    db.execute("""CREATE TABLE IF NOT EXISTS business_expenses(
        id INTEGER PRIMARY KEY, service_id INTEGER REFERENCES business_services(id),
        amount INTEGER NOT NULL CHECK(amount>0), created INTEGER NOT NULL, note TEXT NOT NULL,
        reference TEXT NOT NULL UNIQUE)""")
    db.execute("""CREATE TABLE IF NOT EXISTS business_budget(
        id INTEGER PRIMARY KEY CHECK(id=1), daily INTEGER NOT NULL, monthly INTEGER NOT NULL)""")
def money(value):
    try:
        d=Decimal(str(value))
        if not d.is_finite() or not 0<=d<=100000000 or d!=d.quantize(Decimal('.01')): raise ValueError()
        return int(d*100)
    except (InvalidOperation,ValueError): raise ValueError('Укажите сумму в рублях с точностью до копеек')
def add(db,form):
    supplier=form.get('supplier','').strip()
    name=form.get('name','').strip()
    kind=form.get('kind','')
    if not 1<=len(supplier)<=100 or not 1<=len(name)<=100 or kind not in KINDS: raise ValueError('Некорректные параметры услуги')
    raw=form.get('expires','')
    try: expires=int(datetime.strptime(raw,'%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())+86400 if raw else None
    except ValueError: raise ValueError('Некорректная дата')
    with db:
        init(db)
        db.execute('INSERT INTO business_services(supplier,name,kind,expires,created) VALUES(?,?,?,?,?)',(supplier,name,kind,expires,int(time.time())))
def budget(db,form):
    daily,monthly=money(form.get('daily','')),money(form.get('monthly',''))
    with db:
        init(db)
        db.execute('INSERT INTO business_budget VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET daily=excluded.daily,monthly=excluded.monthly',(daily,monthly))
def record(db,form):
    amount=money(form.get('amount',''))
    ref=form.get('reference','').strip()
    note=form.get('note','').strip()
    if not amount or not 1<=len(ref)<=100 or len(note)>300: raise ValueError('Укажите сумму и уникальный номер операции')
    try: sid=int(form.get('service',''))
    except ValueError: raise ValueError('Выберите услугу')
    with db:
        init(db)
        if not db.execute('SELECT 1 FROM business_services WHERE id=?',(sid,)).fetchone(): raise ValueError('Услуга не найдена')
        db.execute('INSERT INTO business_expenses(service_id,amount,created,note,reference) VALUES(?,?,?,?,?)',(sid,amount,int(time.time()),note,ref))
def state(db):
    init(db)
    now=int(time.time())
    today=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    month=today.replace(day=1)
    limits=db.execute('SELECT daily,monthly FROM business_budget WHERE id=1').fetchone() or (0,0)
    spent=[db.execute('SELECT coalesce(sum(amount),0) FROM business_expenses WHERE created>=?',(int(start.timestamp()),)).fetchone()[0] for start in (today,month)]
    services=[]
    for row in db.execute('SELECT * FROM business_services ORDER BY id DESC'):
        item=dict(row)
        item['health']='archived' if item['status']=='archived' else 'expired' if item['expires'] and item['expires']<=now else 'soon' if item['expires'] and item['expires']<=now+7*86400 else 'active'
        item['expiry_date']=datetime.fromtimestamp(item['expires']-1,timezone.utc).strftime('%Y-%m-%d') if item['expires'] else '—'
        services.append(item)
    return dict(services=services,limits=list(limits),spent=spent,over=[bool(l and s>=l) for l,s in zip(limits,spent)],expired=sum(x['health']=='expired' for x in services),soon=sum(x['health']=='soon' for x in services),expenses=[dict(x) for x in db.execute('SELECT e.*,s.name FROM business_expenses e JOIN business_services s ON s.id=e.service_id ORDER BY e.id DESC LIMIT 100')])
def archive(db,sid):
    with db:
        init(db)
        if not db.execute("UPDATE business_services SET status='archived' WHERE id=? AND status='active'",(sid,)).rowcount: raise ValueError('Услуга не найдена или уже в архиве')
