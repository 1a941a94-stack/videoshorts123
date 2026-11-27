"""Descriptive reporting only; no automated account or distribution decisions."""
from datetime import datetime, timezone, timedelta

DIMENSIONS={
    'platform':"a.platform",
    'account':"a.name",
    'topic':"coalesce(nullif(a.topic,''),'Без категории')",
    'campaign':"coalesce(nullif(c.campaign,''),'Без кампании')",
    'source':"CASE WHEN c.video_id LIKE 'tg\\_%' ESCAPE '\\' THEN 'Telegram' WHEN c.video_id LIKE 'local\\_%' ESCAPE '\\' THEN 'Локальный файл' WHEN v.url LIKE 'https://www.youtube.com/%' THEN 'YouTube' ELSE 'Другой источник' END",
    'clip':"cast(c.id as text)"
}
def state(db,days=30,dimension='campaign'):
    if days not in (7,30,90,0) or dimension not in DIMENSIONS: raise ValueError('Invalid report parameters')
    start=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=max(0,days-1))
    cutoff=int(start.timestamp()) if days else 0
    expr=DIMENSIONS[dimension]
    base=""" FROM publications p JOIN accounts a ON a.id=p.account_id
        JOIN clips c ON c.id=p.clip_id JOIN videos v ON v.id=c.video_id
        LEFT JOIN measurements m ON m.publication_id=p.id
        WHERE p.status='sent' AND p.updated>=?"""
    fields="""count(*) published,count(m.publication_id) measured,
        coalesce(sum(m.views),0) views,coalesce(sum(m.accepted_views),0) accepted,
        coalesce(sum(m.revenue_kopecks),0) accrued"""
    totals=dict(db.execute('SELECT '+fields+base,(cutoff,)).fetchone())
    rows=[dict(x) for x in db.execute('SELECT '+expr+' AS label,'+fields+base+' GROUP BY 1 ORDER BY label LIMIT 1000',(cutoff,))]
    for row in [totals,*rows]:
        row['average_views']=row['views']/row['measured'] if row['measured'] else None
        row['coverage']=100*row['measured']/row['published'] if row['published'] else None
        row['accepted_pct']=100*row['accepted']/row['views'] if row['views'] else None
    return dict(days=days,dimension=dimension,rows=rows,totals=totals,
        statuses=dict(db.execute('SELECT status,count(*) FROM publications GROUP BY status')))
