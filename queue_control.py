import json
import time

def explain(row):
    raw=str(row['error'] or row['ad_result'] or '')
    lower=raw.lower()
    if 'tesseract' in lower or 'ocr unavailable' in lower:
        return dict(kind='system',title='Не готово распознавание текста',help='Проверьте Tesseract и языки rus/eng.',retry=True)
    if 'no space' in lower or 'disk space' in lower:
        return dict(kind='system',title='Недостаточно места',help='Освободите место на диске.',retry=True)
    if any(x in lower for x in ('background missing','banner not found','campaign unavailable','no eligible active banner')):
        return dict(kind='settings',title='Недоступен материал оформления',help='Проверьте фон и рекламную кампанию.',retry=True)
    if any(x in lower for x in ('timed out','timeout','connection reset','temporary failure','http error 503','http error 502','http error 429')):
        return dict(kind='temporary',title='Временная ошибка соединения или обработки',help='Повторите обработку позже.',retry=True)
    if row['status']=='ad_review':
        return dict(kind='review',title='Неоднозначная проверка рекламы',help='Проверьте исходник; повтор не отключает фильтр.',retry=True)
    if row['status']=='duplicate':
        return dict(kind='filtered',title='Обнаружен дубликат',help='Повторная обработка не требуется.',retry=False)
    if row['status']=='ad_rejected':
        return dict(kind='filtered',title='Обнаружена сторонняя реклама',help='Исходник исключён фильтром.',retry=False)
    if row['status']=='failed':
        return dict(kind='error',title='Не удалось обработать видео',help='Откройте технические подробности.',retry=True)
    return dict(kind='normal',title='',help='',retry=False)

def retry_task(db,cid):
    from production_runs import create
    row=db.execute('SELECT * FROM clips WHERE id=?',(cid,)).fetchone()
    if not row or row['status'] not in ('failed','ad_review'): raise ValueError('Task cannot be retried')
    if not row['task_snapshot']: raise ValueError('У старой задачи нет сохранённых настроек. Используйте новую конфигурацию.')
    task=json.loads(row['task_snapshot'])
    config={**task,'auto_search':False,'only_ids':[cid],'name':'Повтор задачи #'+str(cid)}
    run_id=create(db,1,config)
    with db:
        db.execute("UPDATE clips SET status='pending',run_id=?,attempts=0,error=NULL,updated=? WHERE id=?",(run_id,int(time.time()),cid))
    return run_id

def queue_action(db,cid,action):
    with db:
        row=db.execute('SELECT status FROM clips WHERE id=?',(cid,)).fetchone()
        if not row: raise ValueError('Task not found')
        state=row['status']
        if action=='priority' and state=='pending':
            db.execute('UPDATE clips SET priority=priority+1 WHERE id=?',(cid,))
        elif action=='cancel' and state=='pending':
            db.execute("UPDATE clips SET status='cancelled',updated=? WHERE id=?",(int(time.time()),cid))
        elif action=='restore' and state=='cancelled':
            db.execute("UPDATE clips SET status='pending',run_id=NULL,updated=? WHERE id=?",(int(time.time()),cid))
        else: raise ValueError('Invalid task operation')
