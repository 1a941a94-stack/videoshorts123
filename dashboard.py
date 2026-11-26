"""Local-only dashboard. Do not expose directly to the Internet."""
import json
import sqlite3
import time
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, abort, send_file, session, jsonify
from pipeline import connect, add_source, DEFAULTS
from banners import Banner
from publishing import init, add_account, enqueue, approve, measure

ROOT=Path(__file__).resolve().parent

def create_app(root=ROOT):
    root=Path(root).resolve()
    app=Flask(__name__,template_folder=str(ROOT/'templates'),static_folder=str(ROOT/'static'))
    app.secret_key=secrets.token_hex(32)
    app.config.update(MAX_CONTENT_LENGTH=16*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    dbpath=root/'clipfactory.sqlite3'
    out=root/'output'
    config=root/'settings.json'
    campaigns=root/'campaigns.json'
    assets=root/'assets'
    lock=threading.Lock()
    job={'process':None,'action':None,'log':None,'started':None,'finished':None}

    def read_json(path,default):
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

    def save_json(path,value):
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(path)

    @app.before_request
    def guard():
        if request.host.split(':')[0] not in ('localhost','127.0.0.1'): abort(403)
        if 'csrf' not in session: session['csrf']=secrets.token_hex(24)
        if request.method=='POST' and not secrets.compare_digest(request.form.get('csrf',''),session['csrf']): abort(403)

    @app.get('/api/job-status')
    def job_status():
        with lock:
            proc=job['process']
            result=proc.poll() if proc else None
            running=proc is not None and result is None
            if proc and not running and job['finished'] is None:
                job['finished']=time.time()
            started=job['started']
            elapsed=round((job['finished'] or time.time())-started) if started else 0
            log=''
            age=None
            if job['log'] and job['log'].exists():
                path=job['log']
                age=max(0,round(time.time()-path.stat().st_mtime))
                with path.open('rb') as fp:
                    fp.seek(max(0,path.stat().st_size-65536))
                    log=fp.read().decode('utf-8','replace')
            action=job['action']
        done=total=None
        stage=detail=''
        lines=[]
        for line in log.splitlines():
            if line.startswith('CF_PROGRESS '):
                try: done,total=map(int,line.split()[1:])
                except ValueError: pass
            elif line.startswith('CF_STAGE '):
                try:
                    event=json.loads(line[9:])
                    stage=event.get('stage','')
                    detail=event.get('detail','')
                except (ValueError,AttributeError): pass
            else: lines.append(line)
        db=connect(dbpath)
        try:
            stats=dict(db.execute('SELECT status,count(*) FROM clips GROUP BY status').fetchall())
            stats['videos']=db.execute('SELECT count(*) FROM videos').fetchone()[0]
            active=[dict(r) for r in db.execute("SELECT c.id,v.title FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.status='running'")]
        finally: db.close()
        response=jsonify(running=running,result=result,action=action,elapsed=elapsed,log_age=age,
            done=done,total=total,stage=stage,detail=detail,stats=stats,active=active,log='\n'.join(lines)[-18000:])
        response.headers['Cache-Control']='no-store'
        return response

    @app.get('/')
    def index():
        db=connect(dbpath)
        try:
            sources=db.execute('SELECT * FROM sources ORDER BY id DESC').fetchall()
            videos=db.execute('SELECT * FROM videos ORDER BY checked DESC LIMIT 100').fetchall()
            clips=db.execute('SELECT c.*,v.title FROM clips c JOIN videos v ON v.id=c.video_id ORDER BY c.id DESC LIMIT 100').fetchall()
            stats=dict(db.execute('SELECT status,count(*) FROM clips GROUP BY status').fetchall())
            total=db.execute('SELECT count(*) FROM videos').fetchone()[0]
        finally: db.close()
        with lock:
            proc=job['process']
            running=proc is not None and proc.poll() is None
            result=proc.poll() if proc else None
            log=''
            if job['log'] and job['log'].exists():
                with job['log'].open('rb') as fp:
                    fp.seek(max(0,job['log'].stat().st_size-12000))
                    log=fp.read().decode('utf-8','replace')
        return render_template('dashboard.html',sources=sources,videos=videos,clips=clips,stats=stats,total=total,
            running=running,result=result,log=log,action=job['action'],csrf=session['csrf'],
            campaigns=read_json(campaigns,{'campaigns':[]})['campaigns'],settings={**DEFAULTS,**read_json(config,{})})

    @app.post('/sources')
    def source():
        query=request.form.get('query','').strip()
        if not query or len(query)>500: abort(400)
        db=connect(dbpath)
        try: add_source(db,query)
        finally: db.close()
        return redirect(url_for('index')+'#sources')

    @app.post('/sources/<int:sid>/toggle')
    def toggle(sid):
        db=connect(dbpath)
        try:
            with db: db.execute('UPDATE sources SET enabled=1-enabled WHERE id=?',(sid,))
        finally: db.close()
        return redirect(url_for('index')+'#sources')

    @app.post('/settings')
    def settings():
        try:
            values={k:type(v)(request.form[k]) for k,v in DEFAULTS.items()}
            import math
            if not all(math.isfinite(v) for v in values.values()): raise ValueError()
            if not (1<=values['limit']<=100 and 15<=values['length']<=120 and 1<=values['count']<=10 and 0<=values['threshold']<=1 and 0<=values['min_views'] and values['length']<=values['min_duration']<=values['max_duration']<=86400 and 0<=values['refresh_hours']<=720 and 1<=values['delay']<=60): raise ValueError()
        except (ValueError,KeyError): abort(400,'Invalid settings')
        with lock: save_json(config,values)
        return redirect(url_for('index')+'#settings')

    @app.post('/campaigns')
    def add_campaign():
        upload=request.files.get('image')
        suffix=Path(upload.filename or '').suffix.lower() if upload else ''
        if suffix not in ('.png','.jpg','.jpeg','.webp'): abort(400,'Invalid image')
        name=request.form.get('name','').strip()
        if not name or len(name)>100: abort(400)
        assets.mkdir(exist_ok=True)
        path=assets/(secrets.token_hex(12)+suffix)
        upload.save(path)
        try:
            import cv2
            if cv2.imread(str(path)) is None: raise ValueError('Invalid image')
            spec=Banner(path,name=name,width=int(request.form['width']),height=int(request.form['height']),
                position=request.form['position'],margin=int(request.form['margin']),opacity=float(request.form['opacity']),
                start=float(request.form['start']),end=float(request.form['end']) if request.form.get('end') else None)
            weight=float(request.form['weight'])
            import math
            if not math.isfinite(weight) or not 0<weight<=100: raise ValueError('Invalid weight')
            row={**vars(spec),'path':str(path.relative_to(root)),'weight':weight,'enabled':True}
            with lock:
                data=read_json(campaigns,{'campaigns':[]})
                if any(x['name']==name for x in data['campaigns']): raise ValueError('Duplicate campaign')
                data['campaigns'].append(row)
                save_json(campaigns,data)
        except (ValueError,KeyError) as exc:
            path.unlink(missing_ok=True)
            abort(400,str(exc))
        return redirect(url_for('index')+'#campaigns')

    @app.post('/campaigns/<int:cid>/toggle')
    def toggle_campaign(cid):
        with lock:
            data=read_json(campaigns,{'campaigns':[]})
            if not 0<=cid<len(data['campaigns']): abort(404)
            row=data['campaigns'][cid]
            row['enabled']=not row.get('enabled',True)
            save_json(campaigns,data)
        return redirect(url_for('index')+'#campaigns')

    @app.post('/jobs/<action>')
    def start_job(action):
        if action not in ('scan','work','retry'): abort(404)
        with lock:
            if job['process'] and job['process'].poll() is None: abort(409,'Job already running')
            cmd=[sys.executable,'-u',str(ROOT/'pipeline.py'),'--db',str(dbpath)]
            if config.exists(): cmd+=['--config',str(config)]
            cmd.append(action)
            if action=='work':
                try: limit=int(request.form.get('limit','10'))
                except ValueError: abort(400)
                if not 1<=limit<=100: abort(400)
                cmd+=['--limit',str(limit),'--out',str(out)]
                if request.form.get('ads')=='1':
                    if not campaigns.exists(): abort(400,'Create a campaign first')
                    cmd+=['--campaigns',str(campaigns)]
            env=os.environ.copy()
            env['CLIP_CAPTIONS']='1' if request.form.get('captions')=='1' else '0'
            env['CLIP_SMART_SPEECH']='1' if request.form.get('smart_speech')=='1' else '0'
            log=root/'dashboard-job.log'
            with log.open('wb') as fp:
                proc=subprocess.Popen(cmd,cwd=root,stdout=fp,stderr=subprocess.STDOUT,env=env)
            job.update(process=proc,action=action,log=log,started=time.time(),finished=None)
        return redirect(url_for('index'))

    @app.get('/publishing')
    def publication_page():
        db=init(connect(dbpath))
        try:
            accounts=db.execute('SELECT * FROM accounts ORDER BY id').fetchall()
            drafts=db.execute("""SELECT p.*,a.name account_name,c.campaign,m.views,m.accepted_views,m.revenue_kopecks
                FROM publications p JOIN accounts a ON a.id=p.account_id JOIN clips c ON c.id=p.clip_id
                LEFT JOIN measurements m ON m.publication_id=p.id ORDER BY p.id DESC LIMIT 200""").fetchall()
            ready=db.execute("SELECT id FROM clips WHERE status='done' ORDER BY id DESC LIMIT 200").fetchall()
            totals=db.execute("SELECT coalesce(sum(views),0),coalesce(sum(accepted_views),0),coalesce(sum(revenue_kopecks),0) FROM measurements").fetchone()
            return render_template('publishing.html',accounts=accounts,drafts=drafts,ready=ready,totals=totals,csrf=session['csrf'])
        finally: db.close()

    @app.post('/publishing/<action>')
    def publication_action(action):
        db=init(connect(dbpath))
        try:
            if action=='account':
                add_account(db,request.form['name'],request.form['platform'],request.form['destination'],
                    request.form['token_env'],request.form.get('topic',''),int(request.form.get('daily','2')))
            elif action=='toggle':
                with db: db.execute('UPDATE accounts SET enabled=1-enabled WHERE id=?',(int(request.form['id']),))
            elif action=='draft':
                enqueue(db,int(request.form['account']),int(request.form['clip']),request.form['caption'],int(request.form.get('scheduled') or time.time()))
            elif action=='approve':
                if not approve(db,int(request.form['id'])): abort(409)
            elif action=='measure':
                measure(db,int(request.form['id']),int(request.form['views']),int(request.form['accepted']),int(request.form['kopecks']))
            elif action=='send':
                with lock:
                    if job['process'] and job['process'].poll() is None: abort(409,'Job already running')
                    log=root/'dashboard-job.log'
                    with log.open('wb') as fp:
                        proc=subprocess.Popen([sys.executable,'-u',str(ROOT/'publishing.py'),'--root',str(root),'send'],cwd=root,stdout=fp,stderr=subprocess.STDOUT)
                    job.update(process=proc,action='send',log=log,started=time.time(),finished=None)
            else: abort(404)
        except (ValueError,KeyError,sqlite3.IntegrityError): abort(400,'Invalid publication settings')
        finally: db.close()
        return redirect(url_for('publication_page'))

    @app.get('/clips/<int:cid>/video')
    def video(cid):
        db=connect(dbpath)
        try: row=db.execute("SELECT output FROM clips WHERE id=? AND status='done'",(cid,)).fetchone()
        finally: db.close()
        if not row or not row['output']: abort(404)
        path=(root/row['output']).resolve()
        if not path.is_relative_to(out.resolve()) or not path.is_file() or path.suffix!='.mp4': abort(404)
        return send_file(path,mimetype='video/mp4',conditional=True)
    return app

if __name__=='__main__':
    create_app().run(host='127.0.0.1',port=8080,debug=False)
