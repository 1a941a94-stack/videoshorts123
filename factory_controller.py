"""Production-only controller. Does not publish, purchase services or modify accounts."""
import time
import shutil

def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS factory_controller(
        id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
        next_check INTEGER NOT NULL DEFAULT 0, last_check INTEGER,
        detail TEXT NOT NULL DEFAULT '', run_id INTEGER)""")
    db.execute("INSERT OR IGNORE INTO factory_controller(id) VALUES(1)")

def state(db):
    init(db)
    return dict(db.execute('SELECT * FROM factory_controller WHERE id=1').fetchone())

def enable(db,value):
    from business_factory import init as business_init,event
    with db:
        init(db)
        business_init(db)
        db.execute("UPDATE factory_controller SET enabled=?,next_check=0,detail=? WHERE id=1",
                   (int(value),'Запрошен запуск' if value else 'Остановлен владельцем'))
        event(db,'controller','Автопополнение включено' if value else 'Автопополнение остановлено')

def record(db,detail,delay=60,run_id=None):
    from business_factory import init as business_init,event
    now=int(time.time())
    with db:
        init(db)
        business_init(db)
        old=state(db)
        db.execute("UPDATE factory_controller SET last_check=?,next_check=?,detail=?,run_id=? WHERE id=1",
                   (now,now+delay,detail,run_id if run_id is not None else old['run_id']))
        if old['detail']!=detail: event(db,'controller',detail)

def decision(db,root,configs):
    from business_factory import load,forecast
    from business_resources import state as resources
    cfg=load(db)
    item=configs.get(cfg['configuration'])
    if not item: return None,'Сохраните конфигурацию монтажа',300
    res=resources(db)
    if any(res['over']): return None,'Достигнут бюджет инфраструктуры',300
    if shutil.disk_usage(root).free<3*1024**3: return None,'Недостаточно места на диске (минимум 3 ГБ)',300
    import psutil
    if psutil.virtual_memory().available<512*1024**2: return None,'Недостаточно свободной оперативной памяти',120
    ready=db.execute("""SELECT count(*) FROM clips c WHERE c.status='done' AND c.output IS NOT NULL
        AND NOT EXISTS(SELECT 1 FROM publications p WHERE p.clip_id=c.id AND p.status!='cancelled')""").fetchone()[0]
    missing=max(0,forecast(cfg)['reserve']-ready)
    if not missing: return None,'Резерв заполнен',60
    pending=db.execute("SELECT count(*) FROM clips WHERE status='pending' AND mode=?",(item['mode'],)).fetchone()[0]
    from diagnostics import readiness
    issues=[x['name'] for x in readiness(root,item['mode']) if x['required'] and not x['ok']]
    if issues: return None,'Не готова система: '+', '.join(issues),300
    if item['mode']=='short' and pending<missing and item.get('auto_search'):
        from incoming_media import ingest
        db.commit()
        result=ingest(db,root,missing-pending)
        pending+=result['added']
        if result['errors'] or result['added']:
            from business_factory import event
            with db: event(db,'intake',f"Входящие материалы: добавлено {result['added']}, ошибок {result['errors']}")
    now=int(time.time())
    remote=bool(item.get('auto_search') and (db.execute('SELECT 1 FROM sources WHERE enabled=1 AND auto_allowed=1 AND coalesce(last_scan,0)<=? LIMIT 1',(now-3600,)).fetchone() or (item['mode']=='short' and db.execute('SELECT 1 FROM telegram_channels WHERE enabled=1 AND auto_allowed=1 AND coalesce(last_scan,0)<=? LIMIT 1',(now-3600,)).fetchone())))
    if not pending and not remote: return None,'Ожидание разрешённых исходников или следующего сканирования',300
    from run_configs import resolve
    snap=resolve(root,item)
    # This controller only consumes the existing authorized production queue.
    snap['auto_search']=remote
    snap['approved_sources_only']=True
    snap['name']='Автопополнение резерва'
    return (min(1000,missing,missing if remote else pending),snap),'Подготовлена производственная партия',60


def interrupted_run(db,root,current):
    """Called only while holding the exclusive production lock."""
    if not current['enabled'] or current['run_id'] is None or (root/'factory.stop').exists():
        return None
    row=db.execute("SELECT id,mode,status FROM production_runs WHERE id=? AND status IN ('queued','running')",(current['run_id'],)).fetchone()
    if not row:
        return None
    return dict(row)
