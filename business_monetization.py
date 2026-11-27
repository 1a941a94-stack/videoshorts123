"""Local revenue ledger; no external submissions or payment initiation."""
import json
import time
from decimal import Decimal
from pathlib import Path
from business_resources import money

def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS business_partners(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, note TEXT NOT NULL DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS business_campaign_terms(
        campaign TEXT PRIMARY KEY, partner_id INTEGER NOT NULL REFERENCES business_partners(id),
        cpm INTEGER NOT NULL CHECK(cpm>=0), note TEXT NOT NULL DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS business_payouts(
        id INTEGER PRIMARY KEY, partner_id INTEGER NOT NULL REFERENCES business_partners(id),
        amount INTEGER NOT NULL CHECK(amount>0), reference TEXT NOT NULL, created INTEGER NOT NULL,
        UNIQUE(partner_id,reference))""")
def campaigns(root):
    path=Path(root)/'campaigns.json'
    return [x['name'] for x in json.loads(path.read_text(encoding='utf-8'))['campaigns']] if path.exists() else []
def partner(db,form):
    name=form.get('name','').strip()
    note=form.get('note','').strip()
    if not 1<=len(name)<=100 or len(note)>500: raise ValueError('Некорректное название или комментарий')
    with db:
        init(db)
        db.execute('INSERT INTO business_partners(name,note) VALUES(?,?)',(name,note))
def terms(db,root,form):
    name=form.get('campaign','')
    pid=int(form.get('partner',''))
    cpm=money(form.get('cpm',''))
    note=form.get('note','').strip()
    if name not in campaigns(root) or len(note)>500: raise ValueError('Выберите существующую рекламную кампанию')
    with db:
        init(db)
        if not db.execute('SELECT 1 FROM business_partners WHERE id=?',(pid,)).fetchone(): raise ValueError('Партнёр не найден')
        # Never silently reattribute historical revenue to another partner.
        old=db.execute('SELECT partner_id FROM business_campaign_terms WHERE campaign=?',(name,)).fetchone()
        if old and old[0]!=pid: raise ValueError('Для другого партнёра создайте новую рекламную кампанию')
        db.execute("""INSERT INTO business_campaign_terms VALUES(?,?,?,?)
            ON CONFLICT(campaign) DO UPDATE SET cpm=excluded.cpm,note=excluded.note""",(name,pid,cpm,note))
def payout(db,form):
    pid=int(form.get('partner',''))
    amount=money(form.get('amount',''))
    ref=form.get('reference','').strip()
    if not amount or not 1<=len(ref)<=100: raise ValueError('Укажите полученную сумму и номер выплаты')
    with db:
        init(db)
        if not db.execute('SELECT 1 FROM business_partners WHERE id=?',(pid,)).fetchone(): raise ValueError('Партнёр не найден')
        db.execute('INSERT INTO business_payouts(partner_id,amount,reference,created) VALUES(?,?,?,?)',(pid,amount,ref,int(time.time())))
def state(db):
    init(db)
    partners=[dict(x) for x in db.execute('SELECT * FROM business_partners ORDER BY name')]
    rows=[dict(x) for x in db.execute("""SELECT t.*,b.name partner_name,
        (SELECT count(*) FROM publications p JOIN clips c ON c.id=p.clip_id WHERE c.campaign=t.campaign AND p.status='sent') published,
        (SELECT coalesce(sum(m.accepted_views),0) FROM measurements m JOIN publications p ON p.id=m.publication_id JOIN clips c ON c.id=p.clip_id WHERE c.campaign=t.campaign AND p.status='sent') accepted,
        (SELECT coalesce(sum(m.revenue_kopecks),0) FROM measurements m JOIN publications p ON p.id=m.publication_id JOIN clips c ON c.id=p.clip_id WHERE c.campaign=t.campaign AND p.status='sent') accrued
        FROM business_campaign_terms t JOIN business_partners b ON b.id=t.partner_id ORDER BY t.campaign""")]
    for row in rows: row['estimate']=int(Decimal(row['accepted'])*row['cpm']/1000)
    for p in partners:
        p['accrued']=sum(x['accrued'] for x in rows if x['partner_id']==p['id'])
        p['paid']=db.execute('SELECT coalesce(sum(amount),0) FROM business_payouts WHERE partner_id=?',(p['id'],)).fetchone()[0]
        p['balance']=p['accrued']-p['paid']
    payouts=[dict(x) for x in db.execute('SELECT p.*,b.name partner_name FROM business_payouts p JOIN business_partners b ON b.id=p.partner_id ORDER BY p.id DESC LIMIT 100')]
    links=[dict(x) for x in db.execute("""SELECT p.id,p.url,a.name account_name,c.campaign,t.partner_id,m.accepted_views,m.revenue_kopecks
        FROM publications p JOIN clips c ON c.id=p.clip_id JOIN accounts a ON a.id=p.account_id
        JOIN business_campaign_terms t ON t.campaign=c.campaign LEFT JOIN measurements m ON m.publication_id=p.id
        WHERE p.status='sent' ORDER BY p.id DESC LIMIT 200""")]
    return dict(partners=partners,campaigns=rows,payouts=payouts,links=links,accrued=sum(x['accrued'] for x in rows),paid=sum(p['paid'] for p in partners),estimate=sum(x['estimate'] for x in rows))
