"""Exclusive local production supervisor with persistent daily accounting."""
import argparse
import json
import shutil
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from pipeline import connect, scan, process, DEFAULTS
from filelock import FileLock, Timeout
import psutil

def day_start():
    return int(datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())

def remaining(db, limit):
    return max(0,limit-db.execute("SELECT count(*) FROM clips WHERE status='done' AND updated>=?",(day_start(),)).fetchone()[0])

def recover(db):
    with db:
        db.execute("UPDATE clips SET status=CASE WHEN attempts<3 THEN 'pending' ELSE 'failed' END,error='Interrupted during processing',updated=? WHERE status='running'",(int(time.time()),))

def retry(db):
    with db:
        db.execute("UPDATE clips SET status='pending',updated=? WHERE status='failed' AND attempts<3 AND updated<=?",(int(time.time()),int(time.time())-900))

def capacity(out,min_free_gb,max_cpu):
    return shutil.disk_usage(out).free>=min_free_gb*1024**3 and psutil.cpu_percent(interval=.5)<=max_cpu

def worker(dbpath,out,campaigns):
    db=connect(dbpath)
    try: return process(db,out,campaigns=campaigns)
    finally: db.close()

def run(args):
    dbpath=Path(args.db).resolve()
    out=Path(args.out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    settings=DEFAULTS.copy()
    if args.config: settings.update(json.loads(Path(args.config).read_text(encoding='utf-8')))
    if not (1<=args.workers<=4 and args.daily>0 and args.scan_interval>=60 and args.min_free_gb>=1 and 1<=args.max_cpu<=100): raise ValueError('Invalid supervisor settings')
    db=connect(dbpath)
    try:
        recover(db)
        next_scan=0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            while True:
                if time.monotonic()>=next_scan:
                    print('Scan:',scan(db,settings),flush=True)
                    next_scan=time.monotonic()+args.scan_interval
                retry(db)
                pending=db.execute("SELECT count(*) FROM clips WHERE status='pending'").fetchone()[0]
                count=min(args.workers,remaining(db,args.daily),pending)
                if count and capacity(out,args.min_free_gb,args.max_cpu):
                    futures=[pool.submit(worker,dbpath,out,args.campaigns) for _ in range(count)]
                    for f in futures: f.result()
                elif args.once: break
                else: time.sleep(30)
                if args.once: break
    finally: db.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',default='clipfactory.sqlite3')
    p.add_argument('--out',default='output')
    p.add_argument('--config')
    p.add_argument('--campaigns',type=Path)
    p.add_argument('--daily',type=int,default=30)
    p.add_argument('--workers',type=int,default=1)
    p.add_argument('--scan-interval',type=int,default=3600)
    p.add_argument('--min-free-gb',type=float,default=5)
    p.add_argument('--max-cpu',type=float,default=85)
    p.add_argument('--once',action='store_true')
    args=p.parse_args()
    try:
        with FileLock(str(Path(args.db).resolve())+'.production.lock',timeout=0):
            run(args)
    except Timeout: p.error('Another production process is active')
    except KeyboardInterrupt: print('Stopped')
if __name__=='__main__': main()
