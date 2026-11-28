"""Owner-operated setup for supported official publication adapters."""
import csv
import io
import time

SUPPORTED=('telegram','youtube','instagram')

def create(db,form):
    from business_accounts import import_csv
    platform=form.get('platform','')
    if platform not in SUPPORTED: raise ValueError('Выберите поддерживаемый API')
    dest=form.get('destination','').strip()
    if not dest: raise ValueError('Укажите адрес назначения')
    if platform=='instagram' and (not dest.isascii() or not dest.isdigit() or not 5<=len(dest)<=30):
        raise ValueError('Нужен числовой ID профессионального Instagram')
    name=form.get('name','').strip().lstrip('@')
    buf=io.StringIO(newline='')
    writer=csv.writer(buf)
    writer.writerow(['username','platform','category','timezone','daily_limit','destination','token_env'])
    writer.writerow([name,platform,form.get('category','general'),form.get('timezone','Europe/Moscow'),form.get('daily','2'),dest,form.get('token_env','')])
    added,_=import_csv(db,buf.getvalue().encode('utf-8'))
    if not added: raise ValueError('Аккаунт уже существует')
    return db.execute('SELECT id FROM accounts WHERE name=?',(name,)).fetchone()[0]

def activate(db,aid,form,profiles,now=None):
    from account_sessions import init_checks
    from account_lifecycle import init
    now=int(time.time()) if now is None else int(now)
    profile=form.get('profile','')
    caption=form.get('caption','')
    interval=int(form.get('interval','3600'))
    if form.get('confirm')!='1': raise ValueError('Подтвердите разрешение на публикации')
    if profile not in profiles or not 60<=interval<=86400 or len(caption)>1024:
        raise ValueError('Проверьте профиль, интервал и описание')
    db.commit()
    with db:
        db.execute('BEGIN IMMEDIATE')
        init(db)
        init_checks(db)
        row=db.execute("""SELECT a.platform,l.state,c.ok,c.checked FROM accounts a
            LEFT JOIN account_lifecycle l ON l.account_id=a.id
            LEFT JOIN account_connection_checks c ON c.account_id=a.id WHERE a.id=?""",(aid,)).fetchone()
        if not row or row['platform'] not in SUPPORTED: raise ValueError('Адаптер не поддерживается')
        if row['state'] in ('archived','review','paused'): raise ValueError('Сначала требуется отдельная проверка состояния аккаунта')
        if not row['ok'] or not now-900<=row['checked']<=now: raise ValueError('Выполните успешную проверку API не более 15 минут назад')
        if db.execute("SELECT 1 FROM publications WHERE account_id=? AND status IN ('blocked','browser_blocked','uncertain','sending')",(aid,)).fetchone():
            raise ValueError('Сначала сверить проблемные публикации')
        db.execute("UPDATE accounts SET enabled=1,auto_queue=1,production_profile=?,caption_template=?,interval_seconds=? WHERE id=?",(profile,caption,interval,aid))
        if row['state']!='scheduled':
            db.execute("""INSERT INTO account_lifecycle(account_id,state,updated) VALUES(?,'ready',?)
                ON CONFLICT(account_id) DO UPDATE SET state='ready',start_at=NULL,updated=excluded.updated""",(aid,now))
            db.execute("INSERT INTO account_lifecycle_events(account_id,created,state) VALUES(?,?,'ready')",(aid,now))
