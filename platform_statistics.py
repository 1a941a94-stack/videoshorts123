"""Read-only statistics, separate from advertising settlement."""
import time

def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS platform_statistics(
        publication_id INTEGER NOT NULL REFERENCES publications(id),
        measured INTEGER NOT NULL, views INTEGER NOT NULL,
        likes INTEGER, comments INTEGER,
        PRIMARY KEY(publication_id,measured))""")
    db.execute("""CREATE TABLE IF NOT EXISTS platform_statistics_checks(
        publication_id INTEGER PRIMARY KEY REFERENCES publications(id),
        checked INTEGER NOT NULL, error TEXT)""")

def collect(db,root,limit=5,reader=None,now=None):
    from youtube_publish import read_statistics
    now=int(time.time()) if now is None else int(now)
    init(db)
    rows=db.execute("""SELECT p.id,p.remote_id,a.destination FROM publications p
        JOIN accounts a ON a.id=p.account_id
        LEFT JOIN platform_statistics_checks s ON s.publication_id=p.id
        WHERE a.platform='youtube' AND p.status='sent' AND p.remote_id IS NOT NULL
        AND coalesce(s.checked,0)<=? ORDER BY coalesce(s.checked,0),p.id LIMIT ?""",
        (now-3600,min(5,max(0,limit)))).fetchall()
    db.commit()
    count=0
    for row in rows:
        error=None
        try:
            data=(reader or read_statistics)(root,row['destination'],row['remote_id'])
            values=[data.get(k) for k in ('views','likes','comments')]
            if values[0] is None or any(v is not None and (type(v) is not int or v<0 or v>2**63-1) for v in values):
                raise ValueError('Invalid statistics')
            with db:
                db.execute('INSERT OR REPLACE INTO platform_statistics VALUES(?,?,?,?,?)',(row['id'],now,*values))
            count+=1
        except Exception:
            error='Не удалось подтвердить статистику API'
        with db:
            db.execute('INSERT OR REPLACE INTO platform_statistics_checks VALUES(?,?,?)',(row['id'],now,error))
    return count

def totals(db):
    init(db)
    return dict(db.execute("""SELECT coalesce(sum(s.views),0) views,count(*) publications
        FROM platform_statistics s JOIN publications p ON p.id=s.publication_id
        WHERE p.status='sent' AND s.measured=(SELECT max(t.measured) FROM platform_statistics t WHERE t.publication_id=s.publication_id)""").fetchone())
