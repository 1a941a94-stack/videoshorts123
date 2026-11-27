"""Operational scheduling and explicit review; never clears platform restrictions."""
import time
from datetime import datetime, timezone

LABELS={'new':'Не проверен','ready':'Проверен владельцем','scheduled':'Ожидает даты запуска','paused':'Пауза','review':'Требуется проверка'}
def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS account_lifecycle(
        account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
        state TEXT NOT NULL DEFAULT 'new', start_at INTEGER,
        updated INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS account_lifecycle_events(
        id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
        created INTEGER NOT NULL, state TEXT NOT NULL)""")

def change(db,aid,operation,start_at=None):
    if operation not in ('verify','schedule','pause','review'): raise ValueError('Неизвестная операция')
    now=int(time.time())
    with db:
        db.execute('BEGIN IMMEDIATE')
        init(db)
        a=db.execute('SELECT enabled FROM accounts WHERE id=?',(aid,)).fetchone()
        if not a: raise ValueError('Аккаунт не найден')
        issues=db.execute("SELECT count(*) FROM publications WHERE account_id=? AND status IN ('blocked','browser_blocked','uncertain','sending')",(aid,)).fetchone()[0]
        if operation in ('verify','schedule') and issues: raise ValueError('Сначала сверить проблемные публикации')
        if operation=='schedule':
            if not start_at or start_at<=now: raise ValueError('Укажите будущую дату начала')
            state='scheduled'
        else:
            state={'verify':'ready','pause':'paused','review':'review'}[operation]
            start_at=None
        # Readiness is not authorization, and never enables publication automatically.
        db.execute("""INSERT INTO account_lifecycle(account_id,state,start_at,updated) VALUES(?,?,?,?)
            ON CONFLICT(account_id) DO UPDATE SET state=excluded.state,start_at=excluded.start_at,updated=excluded.updated""",(aid,state,start_at,now))
        if state in ('paused','review'):
            db.execute('UPDATE accounts SET enabled=0 WHERE id=?',(aid,))
        db.execute('INSERT INTO account_lifecycle_events(account_id,created,state) VALUES(?,?,?)',(aid,now,state))

def snapshot(db):
    init(db)
    now=int(time.time())
    counts={'new':0,'ready':0,'scheduled':0,'paused':0,'review':0}
    next_start=None
    for row in db.execute("""SELECT a.id,a.enabled,l.state,l.start_at,
        EXISTS(SELECT 1 FROM publications p WHERE p.account_id=a.id AND p.status IN ('blocked','browser_blocked','uncertain')) AS issue
        FROM accounts a LEFT JOIN account_lifecycle l ON l.account_id=a.id"""):
        state='review' if row['issue'] else row['state'] or 'new'
        if state=='scheduled':
            if row['start_at']<=now: state='ready'
            elif next_start is None or row['start_at']<next_start: next_start=row['start_at']
        counts[state]+=1
    return dict(counts=counts,next_start=next_start)

def decorate(db,accounts):
    init(db)
    now=int(time.time())
    for a in accounts:
        row=db.execute('SELECT state,start_at FROM account_lifecycle WHERE account_id=?',(a['id'],)).fetchone()
        state=row['state'] if row else 'new'
        start=row['start_at'] if row else None
        if a['issues']: state='review'
        elif state=='scheduled' and start<=now: state='ready'
        a.update(lifecycle=state,lifecycle_label=LABELS[state],start_at=start,
                 start_label=datetime.fromtimestamp(start,timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if start else '')
    return accounts
