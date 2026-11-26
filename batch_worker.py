"""One production session, under the existing exclusive pipeline lock."""
import json
import shutil
import time
from pathlib import Path
from production_runs import summary,record,set_status,apply
from source_media import stage

def run(db,root,out,run_id,settings):
    from pipeline import claim,process,scan
    root=Path(root).resolve()
    out=Path(out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    batch=summary(db,run_id)
    if batch['status'] not in ('queued','paused','running'): raise ValueError('Batch is not resumable')
    config=batch['snapshot']
    mode=batch['mode']
    goal=batch['goal']
    stop=root/'factory.stop'
    scanned=0
    max_scans=3
    with db:
        db.execute("UPDATE clips SET status='pending' WHERE run_id=? AND status='running'",(run_id,))
    set_status(db,run_id,'running')
    try:
        while True:
            counts=summary(db,run_id)['counts']
            done=counts.get('done',0)
            print(f'CF_PROGRESS {done} {goal}',flush=True)
            if done>=goal:
                set_status(db,run_id,'completed')
                return
            if stop.exists():
                set_status(db,run_id,'paused','Stopped after current task')
                return
            if shutil.disk_usage(out).free<3*1024**3:
                set_status(db,run_id,'paused','Insufficient disk space')
                return
            row=claim(db,mode,run_id,config.get('only_ids'))
            if row is None:
                if config.get('auto_search') and scanned<max_scans:
                    scanned+=1
                    before=db.execute("SELECT count(*) FROM clips WHERE mode=? AND status='pending'",(mode,)).fetchone()[0]
                    scan(db,settings,mode=mode)
                    after=db.execute("SELECT count(*) FROM clips WHERE mode=? AND status='pending'",(mode,)).fetchone()[0]
                    if after>before: continue
                set_status(db,run_id,'exhausted','No more eligible queued candidates')
                return
            cid=row['id']
            task=json.loads(row['task_snapshot']) if row['task_snapshot'] else config
            with db:
                db.execute('UPDATE clips SET run_id=?,task_snapshot=? WHERE id=?',(run_id,json.dumps(task,ensure_ascii=False),cid))
            record(db,run_id,cid,'running')
            try:
                with apply(task):
                    process(db,out,campaigns=Path(task['campaigns']) if task.get('campaigns') else None,mode=mode,claimed=row)
            except Exception as exc:
                with db:
                    db.execute("UPDATE clips SET status='failed',error=?,updated=? WHERE id=?",(str(exc)[:1000],int(time.time()),cid))
            state=db.execute('SELECT status FROM clips WHERE id=?',(cid,)).fetchone()[0]
            from queue_control import explain
            current=db.execute('SELECT * FROM clips WHERE id=?',(cid,)).fetchone()
            issue=explain(current)
            if state=='failed' and issue['kind']=='temporary' and current['attempts']<3:
                with db:
                    db.execute("UPDATE clips SET status='pending' WHERE id=?",(cid,))
                record(db,run_id,cid,'pending')
                for _ in range(5*current['attempts']):
                    if stop.exists(): break
                    time.sleep(1)
                continue
            record(db,run_id,cid,state)
            if issue['kind']=='system' and state in ('failed','ad_review'):
                set_status(db,run_id,'paused',issue['title'])
                return
            stage('batch_result',f'#{cid}: {state}')
    except BaseException as exc:
        set_status(db,run_id,'failed',str(exc)[:500])
        raise
