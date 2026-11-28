"""Opt-in operational reports to an owner's Telegram chat. Credentials are environment-only."""
import os
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS business_report_deliveries(
        report_key TEXT PRIMARY KEY, created INTEGER NOT NULL, status TEXT NOT NULL,
        finished INTEGER, detail TEXT NOT NULL DEFAULT '')""")

def config():
    token=os.environ.get('CLIP_REPORT_BOT_TOKEN','').strip()
    chat=os.environ.get('CLIP_REPORT_CHAT_ID','').strip()
    enabled=os.environ.get('CLIP_REPORT_ENABLED','0')=='1'
    hour=int(os.environ.get('CLIP_REPORT_HOUR','9'))
    zone=ZoneInfo(os.environ.get('CLIP_REPORT_TIMEZONE','Europe/Moscow'))
    if not 0<=hour<=23: raise ValueError('Invalid report hour')
    if enabled and (not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',token) or not re.fullmatch(r'-?[0-9]+',chat)):
        raise ValueError('Missing report credentials')
    return enabled,token,chat,hour,zone

def status(db):
    init(db)
    try:
        enabled,_,_,hour,zone=config()
        error=''
    except Exception:
        enabled=False; hour=9; zone='—'; error='Проверьте переменные окружения отчётности'
    return dict(enabled=enabled,hour=hour,zone=str(zone),error=error,
        deliveries=[dict(x) for x in db.execute('SELECT * FROM business_report_deliveries ORDER BY created DESC LIMIT 30')])

def rub(amount):
    return f'{amount/100:,.2f} ₽'.replace(',',' ')

def report(db,now):
    from business_resources import init as ri
    from business_monetization import init as mi
    from business_factory import load,forecast
    from factory_controller import state
    ri(db); mi(db)
    end=now.replace(hour=0,minute=0,second=0,microsecond=0)
    start=end-timedelta(days=1)
    bounds=(int(start.timestamp()),int(end.timestamp()))
    def count(sql): return db.execute(sql,bounds).fetchone()[0]
    produced=count("SELECT count(*) FROM clips WHERE status='done' AND updated>=? AND updated<?")
    sent=count("SELECT count(*) FROM publications WHERE status='sent' AND updated>=? AND updated<?")
    spent=count("SELECT coalesce(sum(amount),0) FROM business_expenses WHERE created>=? AND created<?")
    paid=count("SELECT coalesce(sum(amount),0) FROM business_payouts WHERE created>=? AND created<?")
    views,accrued=db.execute("SELECT coalesce(sum(views),0),coalesce(sum(revenue_kopecks),0) FROM measurements").fetchone()
    ready=db.execute("SELECT count(*) FROM clips c WHERE status='done' AND output IS NOT NULL AND NOT EXISTS(SELECT 1 FROM publications p WHERE p.clip_id=c.id AND p.status!='cancelled')").fetchone()[0]
    target=forecast(load(db))['reserve']
    controller=state(db)
    issues=db.execute("SELECT count(*) FROM publications WHERE status IN ('blocked','browser_blocked','uncertain')").fetchone()[0]
    return '\n'.join([
        'ClipFactory — ежедневная сводка',start.strftime('%d.%m.%Y'),
        f'Готовые ролики за день: {produced}',f'Отправлено за день: {sent}',
        f'Выплаты за день: {rub(paid)}',f'Расходы за день: {rub(spent)}',
        f'Денежный результат: {rub(paid-spent)}',
        f'Учтённые просмотры всего: {views}',f'Учтённые начисления всего: {rub(accrued)}',
        f'Свободный резерв: {ready}/{target}',f'Публикации на проверке: {issues}',
        'Автопополнение: '+('включено' if controller['enabled'] else 'остановлено'),
        'Дневные показатели роликов и отправок — по дате обновления; финансы — по дате записи.'
    ])

def resource_alerts(res):
    result=[]
    for label,kind,row in zip(('Дневной','Месячный'),('daily','monthly'),res['budget_health']):
        if row['exhausted']:
            result.append(('budget_'+kind,label+' бюджет исчерпан.'))
        elif row['warning']:
            result.append(('budget_warning_'+kind,f"{label} бюджет: использовано {row['percent']}%, остаток {rub(row['remaining'])}."))
    for health,kind,title in [('expired','expired','Истекли услуги'),('soon','renewal','Истекают в течение 7 дней')]:
        items=[x for x in res['services'] if x['health']==health]
        if items:
            lines=[f"{x['supplier']} — {x['name']} ({x['expiry_date']})" for x in items[:10]]
            result.append((kind,f'{title}: {len(items)}.\n'+'\n'.join(lines)[:1800]))
    return result

def alerts(db,root):
    import shutil
    from business_resources import state
    from business_library import inventory
    from business_factory import load,forecast
    from factory_controller import state as controller_state
    res=state(db)
    result=resource_alerts(res)
    if not controller_state(db)['enabled']: return result
    inv=inventory(db); cfg=load(db)
    if shutil.disk_usage(root).free<3*1024**3: result.append(('disk','Свободно менее 3 ГБ на диске.'))
    if not db.execute("SELECT 1 FROM clips WHERE status='pending' LIMIT 1").fetchone():
        result.append(('queue','Очередь исходников пуста.'))
    if inv['caption'].get('free',0)<forecast(cfg)['daily']:
        result.append(('captions','Запас описаний меньше дневной цели.'))
    return result

def deliver(db,key,message,token,chat):
    import requests
    # Commit a unique claim before network I/O. No blind retry after ambiguous delivery.
    with db:
        init(db)
        cur=db.execute("INSERT OR IGNORE INTO business_report_deliveries(report_key,created,status) VALUES(?,?,'sending')",(key,int(time.time())))
        if not cur.rowcount: return
    try:
        response=requests.post('https://api.telegram.org/bot'+token+'/sendMessage',
            json={'chat_id':chat,'text':message},timeout=(5,20))
        ok=response.ok and response.json().get('ok') is True
        state='sent' if ok else 'failed'
        detail='' if ok else 'Telegram не подтвердил отправку'
    except Exception:
        state='uncertain'; detail='Результат не подтверждён; повтор отключён'
    with db:
        db.execute('UPDATE business_report_deliveries SET status=?,finished=?,detail=? WHERE report_key=?',
                   (state,int(time.time()),detail,key))

def tick(db,root):
    enabled,token,chat,hour,zone=config()
    if not enabled: return
    now=datetime.now(zone)
    day=now.strftime('%Y-%m-%d')
    init(db)
    # An interrupted send is never retried automatically.
    with db:
        db.execute("UPDATE business_report_deliveries SET status='uncertain',detail='Прерванная отправка' WHERE status='sending' AND created<?",(int(time.time())-300,))
    if now.hour>=hour:
        key='daily:'+day
        if not db.execute('SELECT 1 FROM business_report_deliveries WHERE report_key=?',(key,)).fetchone():
            message=report(db,now)
            db.commit()
            deliver(db,key,message,token,chat)
    for kind,message in alerts(db,root):
        db.commit()
        deliver(db,'alert:'+day+':'+kind,'ClipFactory — внимание\n'+message,token,chat)
    db.commit()
