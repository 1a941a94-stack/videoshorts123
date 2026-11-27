"""Read-only PROXY6 infrastructure inventory. Never exposes connection secrets."""
import os
import re
import time
from decimal import Decimal, InvalidOperation
import requests

def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS proxy6_inventory(
        provider_id TEXT PRIMARY KEY, version INTEGER NOT NULL, country TEXT NOT NULL,
        expires INTEGER NOT NULL, active INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS proxy6_snapshot(
        id INTEGER PRIMARY KEY CHECK(id=1), balance TEXT NOT NULL,
        currency TEXT NOT NULL, updated INTEGER NOT NULL)""")

def configured():
    return bool(os.getenv('PROXY6_API_KEY','').strip())

def call(method,params=None):
    if method not in ('getprice','getproxy','getcountry','getcount'):
        raise ValueError('Недопустимый метод PROXY6')
    key=os.getenv('PROXY6_API_KEY','').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,200}',key):
        raise ValueError('Настройте PROXY6_API_KEY')
    try:
        response=requests.get('https://px6.link/api/'+key+'/'+method,params=params or {},
                              timeout=(5,15),allow_redirects=False)
        if response.status_code!=200: raise ValueError('Ошибка HTTP PROXY6')
        data=response.json()
    except (requests.RequestException,ValueError):
        raise ValueError('PROXY6 недоступен или вернул некорректный ответ') from None
    if not isinstance(data,dict) or data.get('status')!='yes':
        raise ValueError('PROXY6 отклонил запрос')
    return data

def balance(data):
    try:
        amount=Decimal(str(data['balance']))
        currency=data['currency']
        if not amount.is_finite() or amount<0 or currency not in ('RUB','USD'):
            raise ValueError()
        return str(amount),currency
    except (KeyError,ValueError,InvalidOperation):
        raise ValueError('Некорректный баланс PROXY6') from None

def refresh(db):
    rows={}
    for page in range(1,101):
        if page>1: time.sleep(.4)
        data=call('getproxy',{'state':'all','page':page,'limit':1000})
        items=data.get('list',{})
        if isinstance(items,dict): items=list(items.values())
        if not isinstance(items,list): raise ValueError('Некорректный список PROXY6')
        for item in items:
            try:
                pid=str(item['id'])
                version=int(item['version'])
                country=str(item.get('country','')).lower()
                expires=int(item['unixtime_end'])
                active=int(item['active'])
                if not pid.isdigit() or version not in (3,4,5,6) or active not in (0,1) or expires<0:
                    raise ValueError()
                rows[pid]=(pid,version,country[:2],expires,active)
            except (KeyError,ValueError,TypeError):
                raise ValueError('Некорректная запись PROXY6') from None
        if len(items)<1000: break
    else: raise ValueError('Слишком большой список PROXY6')
    amount,currency=balance(data)
    with db:
        init(db)
        db.execute('DELETE FROM proxy6_inventory')
        db.executemany('INSERT INTO proxy6_inventory VALUES(?,?,?,?,?)',rows.values())
        db.execute('INSERT OR REPLACE INTO proxy6_snapshot VALUES(1,?,?,?)',(amount,currency,int(time.time())))
        from business_resources import init as init_resources
        init_resources(db)
        now=int(time.time())
        for pid,version,country,expires,active in rows.values():
            name='PROXY6 #'+pid
            db.execute("""INSERT INTO business_services(supplier,name,kind,expires,status,created)
                VALUES('PROXY6',?,'network',?,'active',?)
                ON CONFLICT(supplier,name) DO UPDATE SET expires=excluded.expires""",(name,expires,now))
        # Missing provider records are not deleted: historical expenses remain linked.

    return len(rows)

def state(db):
    init(db)
    snap=db.execute('SELECT * FROM proxy6_snapshot WHERE id=1').fetchone()
    now=int(time.time())
    counts=db.execute("""SELECT count(*),
        coalesce(sum(CASE WHEN active=1 AND expires>? THEN 1 ELSE 0 END),0),
        coalesce(sum(CASE WHEN active=1 AND expires>? AND expires<=? THEN 1 ELSE 0 END),0)
        FROM proxy6_inventory""",(now,now,now+7*86400)).fetchone()
    return dict(configured=configured(),snapshot=dict(snap) if snap else None,total=counts[0],active=counts[1],soon=counts[2])

def quote(count,period,version):
    if not 1<=count<=1000 or not 1<=period<=90 or version not in (3,4,6):
        raise ValueError('Некорректные параметры тарифа')
    data=call('getprice',dict(count=count,period=period,version=version))
    try:
        price=Decimal(str(data['price']))
        if not price.is_finite() or price<0: raise ValueError()
        _,currency=balance(data)
        return str(price),currency
    except (KeyError,ValueError,InvalidOperation):
        raise ValueError('Некорректный тариф PROXY6') from None
