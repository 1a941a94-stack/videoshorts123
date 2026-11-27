"""Business planning layer; existing production and publication queues remain intact."""
from decimal import Decimal, InvalidOperation
import json
import time

DEFAULTS=dict(configuration='',accounts=1,posts=2,reserve=3,investment=0,daily_cost=0,cpm=0,views=0,accepted=100,delay=0)
def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS business_settings(
        id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL, updated INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS business_events(
        id INTEGER PRIMARY KEY, created INTEGER NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL)""")
def load(db):
    init(db)
    row=db.execute('SELECT config FROM business_settings WHERE id=1').fetchone()
    return {**DEFAULTS,**json.loads(row[0])} if row else dict(DEFAULTS)
def event(db,kind,detail):
    db.execute('INSERT INTO business_events(created,kind,detail) VALUES(?,?,?)',(int(time.time()),kind,detail))
def save(db,form,configs):
    cfg=dict(DEFAULTS)
    cfg['configuration']=form.get('configuration','')
    if cfg['configuration'] not in configs: raise ValueError('Выберите конфигурацию производства')
    for k,lo,hi in [('accounts',1,1000),('posts',1,10),('reserve',1,30),('investment',0,100000000),('daily_cost',0,100000000),('cpm',0,1000000),('views',0,100000000),('accepted',0,100),('delay',0,365)]:
        try: value=int(form.get(k,DEFAULTS[k]))
        except (TypeError,ValueError): raise ValueError('Некорректное поле: '+k)
        if not lo<=value<=hi: raise ValueError('Недопустимое значение: '+k)
        cfg[k]=value
    with db:
        init(db)
        db.execute('INSERT INTO business_settings VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config,updated=excluded.updated',(json.dumps(cfg,ensure_ascii=False),int(time.time())))
        event(db,'settings','Сохранена бизнес-конфигурация')
    return cfg
def forecast(cfg):
    daily=cfg['accounts']*cfg['posts']
    revenue=Decimal(daily)*cfg['views']*cfg['accepted']*cfg['cpm']/100000
    net=revenue-cfg['daily_cost']
    from math import ceil
    return dict(daily=daily,reserve=daily*cfg['reserve'],revenue=float(revenue),net=float(net),
        breakeven=cfg['delay']+ceil((cfg['investment']+cfg['daily_cost']*cfg['delay'])/net) if net>0 else None)
def state(db,configs):
    from business_library import inventory
    materials=inventory(db)
    from business_resources import state as resource_state
    resources=resource_state(db)
    from account_lifecycle import snapshot
    lifecycle=snapshot(db)
    from business_calendar import overview, reconcile
    reconcile(db)
    calendar=overview(db)
    from business_monetization import state as monetization_state
    monetization=monetization_state(db)
    from factory_controller import state as controller_state
    controller=controller_state(db)
    cfg=load(db)
    plan=forecast(cfg)
    ready=db.execute("SELECT count(*) FROM clips c WHERE status='done' AND output IS NOT NULL AND NOT EXISTS(SELECT 1 FROM publications p WHERE p.clip_id=c.id)").fetchone()[0]
    sources=db.execute('SELECT count(*) FROM sources WHERE enabled=1').fetchone()[0]+db.execute('SELECT count(*) FROM telegram_channels WHERE enabled=1').fetchone()[0]
    accounts=db.execute("SELECT count(*) FROM accounts WHERE enabled=1 AND platform IN ('telegram','instagram','youtube')").fetchone()[0]
    pending=db.execute("SELECT count(*) FROM clips WHERE status='pending'").fetchone()[0]
    published=db.execute("SELECT count(*) FROM publications WHERE status='sent'").fetchone()[0]
    measured=db.execute('SELECT coalesce(sum(views),0),coalesce(sum(revenue_kopecks),0) FROM measurements').fetchone()
    return dict(controller=controller,monetization=monetization,calendar=calendar,lifecycle=lifecycle,resources=resources,materials=materials,config=cfg,plan=plan,ready=ready,sources=sources,accounts=accounts,pending=pending,published=published,views=measured[0],revenue=measured[1]/100,
        missing=max(0,plan['reserve']-ready),configured=cfg['configuration'] in configs,events=[dict(x) for x in db.execute('SELECT * FROM business_events ORDER BY id DESC LIMIT 20')])
