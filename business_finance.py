"""Read-only management accounting based on recorded receipts and expenses."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal

def state(db,days=30):
    from business_resources import init as resources_init
    from business_monetization import init as monetization_init
    from business_factory import load,forecast
    resources_init(db)
    monetization_init(db)
    cfg=load(db)
    today=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    start=today-timedelta(days=days-1)
    end=today+timedelta(days=1)
    lo,hi=int(start.timestamp()),int(end.timestamp())
    def total(table,where='',params=()):
        return db.execute('SELECT coalesce(sum(amount),0) FROM '+table+where,params).fetchone()[0]
    expenses=total('business_expenses',' WHERE created>=? AND created<?',(lo,hi))
    receipts=total('business_payouts',' WHERE created>=? AND created<?',(lo,hi))
    lifetime_expenses=total('business_expenses')
    lifetime_receipts=total('business_payouts')
    produced=db.execute("""SELECT count(*) FROM clips WHERE status='done' AND output IS NOT NULL AND updated>=? AND updated<?""",(lo,hi)).fetchone()[0]
    # updated is a mutable timestamp, not an immutable production history.
    sent=db.execute("SELECT count(*) FROM publications WHERE status='sent' AND updated>=? AND updated<?",(lo,hi)).fetchone()[0]
    categories=[dict(x) for x in db.execute("""SELECT s.kind,coalesce(sum(e.amount),0) amount
        FROM business_expenses e LEFT JOIN business_services s ON s.id=e.service_id
        WHERE e.created>=? AND e.created<? GROUP BY s.kind ORDER BY amount DESC""",(lo,hi))]
    daily_exp=dict(db.execute("SELECT date(created,'unixepoch'),sum(amount) FROM business_expenses WHERE created>=? AND created<? GROUP BY 1",(lo,hi)))
    daily_in=dict(db.execute("SELECT date(created,'unixepoch'),sum(amount) FROM business_payouts WHERE created>=? AND created<? GROUP BY 1",(lo,hi)))
    running=total('business_payouts',' WHERE created<?',(lo,))-total('business_expenses',' WHERE created<?',(lo,))
    series=[]
    for i in range(days):
        date=(start+timedelta(days=i)).strftime('%Y-%m-%d')
        paid=daily_in.get(date,0)
        spent=daily_exp.get(date,0)
        running+=paid-spent
        series.append(dict(date=date,paid=paid,spent=spent,net=paid-spent,balance=running))
    accrued=db.execute("SELECT coalesce(sum(m.revenue_kopecks),0) FROM measurements m JOIN publications p ON p.id=m.publication_id WHERE p.status='sent'").fetchone()[0]
    scenarios=[]
    for label,mult in [('Пессимистичный',Decimal('.5')),('Базовый',Decimal('1')),('Оптимистичный',Decimal('1.5'))]:
        model=forecast({**cfg,'views':int(cfg['views']*mult)})
        scenarios.append(dict(label=label,**model))
    return dict(days=days,start=start.strftime('%Y-%m-%d'),end=today.strftime('%Y-%m-%d'),expenses=expenses,receipts=receipts,net=receipts-expenses,lifetime_expenses=lifetime_expenses,lifetime_receipts=lifetime_receipts,lifetime_net=lifetime_receipts-lifetime_expenses,accrued=accrued,produced=produced,sent=sent,cost_per_clip=expenses/produced if produced else None,categories=categories,series=series,scenarios=scenarios,roi=(lifetime_receipts-lifetime_expenses)*100/lifetime_expenses if lifetime_expenses else None)
