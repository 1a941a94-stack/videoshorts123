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
from publishing import init, add_account, enqueue, approve, measure, configure_auto, sync_ready

ROOT=Path(__file__).resolve().parent

def create_app(root=ROOT):
    root=Path(root).resolve()
    app=Flask(__name__,template_folder=str(ROOT/'templates'),static_folder=str(ROOT/'static'))
    app.secret_key=secrets.token_hex(32)
    app.config.update(MAX_CONTENT_LENGTH=66*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    dbpath=root/'clipfactory.sqlite3'
    out=root/'output'
    config=root/'settings.json'
    campaigns=root/'campaigns.json'
    assets=root/'assets'
    lock=threading.Lock()
    preview_lock=threading.Lock()
    publisher={'process':None}
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
            telegram_channels=db.execute('SELECT * FROM telegram_channels ORDER BY name').fetchall()
            videos=db.execute('SELECT * FROM videos ORDER BY checked DESC LIMIT 100').fetchall()
            clips=db.execute('SELECT c.*,v.title,v.url FROM clips c JOIN videos v ON v.id=c.video_id ORDER BY c.id DESC LIMIT 100').fetchall()
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
        return render_template('dashboard.html',sources=sources,telegram_channels=telegram_channels,videos=videos,clips=clips,stats=stats,total=total,
            running=running,result=result,log=log,action=job['action'],csrf=session['csrf'],
            production_profiles=__import__('production_profiles').load(root),short_profiles=__import__('short_templates').load(root),backgrounds=sorted(p.name for p in (assets/'backgrounds').glob('*') if p.suffix.lower() in ('.jpg','.mp4','.webm','.mov','.gif')),ad_refs=sorted(p.stem for p in (assets/'ad-references').glob('*.png')),campaigns=read_json(campaigns,{'campaigns':[]})['campaigns'],settings={**DEFAULTS,**read_json(config,{})})

    @app.post('/telegram/channels')
    def telegram_channels_add():
        from telegram_source import add_channels
        db=connect(dbpath)
        try:
            add_channels(db,request.form.get('channels','').splitlines(),int(request.form.get('history','100')),int(request.form.get('views','0')))
        except ValueError as exc: abort(400,str(exc))
        finally: db.close()
        return redirect(url_for('index')+'#telegram')

    @app.post('/telegram/channels/<name>/toggle')
    def telegram_channel_toggle(name):
        db=connect(dbpath)
        try:
            with db:
                if not db.execute('UPDATE telegram_channels SET enabled=1-enabled WHERE name=?',(name,)).rowcount: abort(404)
        finally: db.close()
        return redirect(url_for('index')+'#telegram')

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

    @app.post('/shorts/<int:cid>/authorize')
    def authorize_short(cid):
        from pipeline import approve_short
        if request.form.get('rights')!='1': abort(400,'Confirm permission for commercial reuse')
        db=connect(dbpath)
        try:
            if not approve_short(db,cid): abort(404)
        finally: db.close()
        return redirect(url_for('index')+'#clips')

    @app.post('/ad-references')
    def add_ad_reference():
        import cv2
        import numpy as np
        import re
        name=request.form.get('name','').strip()
        upload=request.files.get('image')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',name) or not upload: abort(400,'Invalid reference')
        image=cv2.imdecode(np.frombuffer(upload.read(),dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
        if image is None or min(image.shape)<20 or max(image.shape)>4000 or image.std()<8: abort(400,'Invalid reference image')
        if max(image.shape)>640:
            ratio=640/max(image.shape)
            image=cv2.resize(image,(round(image.shape[1]*ratio),round(image.shape[0]*ratio)),interpolation=cv2.INTER_AREA)
        if min(image.shape)<20 or image.std()<8: abort(400,'Reference too small after resizing')
        folder=assets/'ad-references'
        with lock:
            if job['process'] and job['process'].poll() is None: abort(409)
            folder.mkdir(parents=True,exist_ok=True)
            if len(list(folder.glob('*.png')))>=50 and not (folder/(name+'.png')).exists(): abort(400,'Reference limit reached')
            ok,data=cv2.imencode('.png',image)
            if not ok: abort(400)
            temp=folder/(name+'.tmp')
            temp.write_bytes(data.tobytes())
            temp.replace(folder/(name+'.png'))
        return redirect(url_for('index')+'#ad-references')

    @app.post('/ad-references/<name>/delete')
    def delete_ad_reference(name):
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',name): abort(400)
        with lock:
            if job['process'] and job['process'].poll() is None: abort(409)
            (assets/'ad-references'/(name+'.png')).unlink(missing_ok=True)
        return redirect(url_for('index')+'#ad-references')

    @app.post('/production-profiles')
    def save_production_profile():
        from production_profiles import save
        from short_templates import load
        with lock:
            try: save(root,request.form.get('name',''),request.form,load(root),[c['name'] for c in read_json(campaigns,{'campaigns':[]})['campaigns']])
            except ValueError as exc: abort(400,str(exc))
        return redirect(url_for('index')+'#production-profiles')

    @app.post('/short-preview')
    def short_preview():
        import tempfile
        from io import BytesIO
        from short_templates import validate
        from short_media import render_short
        from quality import inspect,verify
        from banners import choose
        if not preview_lock.acquire(blocking=False): abort(409,'Preview already running')
        try:
            spec=validate(request.form)
            background=''
            if spec['background']:
                p=assets/'backgrounds'/spec['background']
                if not p.is_file(): abort(400,'Background missing')
                background=str(p)
            with tempfile.TemporaryDirectory() as folder:
                folder=Path(folder)
                source=folder/'source.mp4'
                result=folder/'preview.mp4'
                upload=request.files.get('preview_source')
                if upload and upload.filename:
                    if Path(upload.filename).suffix.lower() not in ('.mp4','.mov','.webm','.mkv'): abort(400,'Unsupported source format')
                    upload.save(source)
                else:
                    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=30','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','5','-c:v','libx264','-threads','2','-c:a','aac',str(source)],check=True,timeout=30)
                meta=inspect(source)
                streams=meta.get('streams',[])
                video=next((s for s in streams if s.get('codec_type')=='video'),None)
                if not video or max(int(video['width']),int(video['height']))>4096: abort(400,'Invalid source dimensions')
                duration=min(5,float(meta['format']['duration']))
                if not .5<=duration<=5: abort(400,'Source must contain at least 0.5 seconds')
                name=request.form.get('preview_campaign','')
                banner=choose(campaigns,duration,campaign=name) if name else None
                render_short(source,duration,result,banner,template=spec,background_path=background,captions=False)
                verify(result,duration,any(s.get('codec_type')=='audio' for s in streams))
                return send_file(BytesIO(result.read_bytes()),mimetype='video/mp4',download_name='preview.mp4',max_age=0)
        except (ValueError,KeyError,OSError,subprocess.SubprocessError):
            abort(400,'Preview failed: check video, template and campaign timing')
        finally: preview_lock.release()

    @app.post('/short-profiles')
    def save_short_profile():
        from short_templates import save
        with lock:
            try: save(root,request.form.get('name',''),request.form)
            except ValueError as exc: abort(400,str(exc))
        return redirect(url_for('index')+'#short-template')

    @app.post('/short-backgrounds')
    def add_short_background():
        import cv2
        import numpy as np
        from banners import MOTION_EXT
        from motion_assets import validate_motion
        upload=request.files.get('image')
        if not upload: abort(400)
        suffix=Path(upload.filename or '').suffix.lower()
        folder=assets/'backgrounds'
        with lock:
            folder.mkdir(parents=True,exist_ok=True)
            if len(list(folder.glob('*')))>=100: abort(400,'Background limit')
            path=folder/(secrets.token_hex(12)+(suffix if suffix in MOTION_EXT else '.jpg'))
            try:
                if suffix in MOTION_EXT:
                    upload.save(path)
                    validate_motion(path)
                else:
                    image=cv2.imdecode(np.frombuffer(upload.read(),dtype=np.uint8),cv2.IMREAD_COLOR)
                    if image is None or max(image.shape[:2])>8000: raise ValueError('Invalid background')
                    ok,data=cv2.imencode('.jpg',image)
                    if not ok: raise ValueError('Invalid image')
                    path.write_bytes(data.tobytes())
            except (ValueError,KeyError,OSError,subprocess.SubprocessError):
                path.unlink(missing_ok=True)
                abort(400,'Invalid background media')
        return redirect(url_for('index')+'#short-template')

    @app.get('/short-backgrounds/<name>')
    def view_short_background(name):
        import re
        if not re.fullmatch(r'[a-f0-9]{24}\.(?:jpg|mp4|webm|mov|gif)',name): abort(404)
        path=assets/'backgrounds'/name
        if not path.is_file(): abort(404)
        return send_file(path,conditional=True)

    @app.post('/short-background')
    def short_background():
        upload=request.files.get('image')
        if not upload: abort(400)
        import cv2
        import numpy as np
        image=cv2.imdecode(np.frombuffer(upload.read(),dtype=np.uint8),cv2.IMREAD_COLOR)
        if image is None or max(image.shape[:2])>8000: abort(400,'Invalid background')
        assets.mkdir(exist_ok=True)
        with lock:
            temp=assets/'short-background.tmp.jpg'
            if not cv2.imwrite(str(temp),image): abort(400)
            temp.replace(assets/'short-background.jpg')
        return redirect(url_for('index')+'#short-template')

    @app.post('/campaigns')
    def add_campaign():
        upload=request.files.get('image')
        suffix=Path(upload.filename or '').suffix.lower() if upload else ''
        from banners import MOTION_EXT,IMAGE_EXT
        if suffix not in IMAGE_EXT | MOTION_EXT: abort(400,'Invalid media')
        name=request.form.get('name','').strip()
        if not name or len(name)>100: abort(400)
        assets.mkdir(exist_ok=True)
        path=assets/(secrets.token_hex(12)+suffix)
        upload.save(path)
        try:
            import cv2
            if suffix in MOTION_EXT:
                from motion_assets import validate_motion
                validate_motion(path)
            elif cv2.imread(str(path)) is None: raise ValueError('Invalid image')
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
        except (ValueError,KeyError,OSError,subprocess.SubprocessError) as exc:
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

    @app.post('/factory/stop')
    def stop_factory():
        with lock:
            if job['action']!='factory' or not job['process'] or job['process'].poll() is not None: abort(409)
            (root/'factory.stop').touch()
        return redirect(url_for('index')+'#factory')

    @app.post('/jobs/<action>')
    def start_job(action):
        if action not in ('scan','work','retry','import-short','scan-telegram','scan-telegram-library','discover-telegram','factory'): abort(404)
        with lock:
            if job['process'] and job['process'].poll() is None: abort(409,'Job already running')
            cmd=[sys.executable,'-u',str(ROOT/'pipeline.py'),'--db',str(dbpath)]
            if config.exists(): cmd+=['--config',str(config)]
            cmd.append(action)
            if action=='factory':
                try: limit=int(request.form.get('limit','100'))
                except ValueError: abort(400)
                if not 1<=limit<=1000: abort(400)
                if not __import__('production_profiles').load(root): abort(400,'Create profiles first')
                (root/'factory.stop').unlink(missing_ok=True)
                cmd+=['--limit',str(limit),'--out',str(out)]
                if request.form.get('continuous')=='1': cmd.append('--continuous')
                if request.form.get('replenish')=='1': cmd.append('--replenish')
            if action=='discover-telegram':
                queries=[q.strip() for q in request.form.get('queries','').splitlines() if q.strip()]
                if len(queries)>20 or any(len(q)>100 for q in queries): abort(400)
                for q in queries: cmd.append('--query='+q)
            if action=='scan-telegram-library' and request.form.get('full')=='1': cmd.append('--full')
            if action=='scan-telegram':
                from telegram_source import channel_name
                try:
                    channel=channel_name(request.form.get('channel',''))
                    limit=int(request.form.get('history','100'))
                    views=int(request.form.get('views','0'))
                    if not 1<=limit<=1000 or views<0: raise ValueError()
                except ValueError: abort(400,'Invalid Telegram scan settings')
                cmd += [channel,'--limit',str(limit),'--min-views',str(views)]
            if action=='import-short':
                from urllib.parse import urlsplit,parse_qs
                import re
                u=urlsplit(request.form.get('url','').strip())
                vid=''
                if u.scheme=='https' and u.hostname in ('youtube.com','www.youtube.com','m.youtube.com'):
                    vid=u.path.split('/')[2] if u.path.startswith('/shorts/') else parse_qs(u.query).get('v',[''])[0] if u.path=='/watch' else ''
                elif u.scheme=='https' and u.hostname=='youtu.be': vid=u.path.strip('/')
                if not re.fullmatch(r'[A-Za-z0-9_-]{11}',vid): abort(400,'Invalid YouTube link')
                cmd.append(vid)
            if action in ('scan','work'):
                mode=request.form.get('mode','long')
                if mode not in ('short','long'): abort(400)
                cmd+=['--mode',mode]
            account=None
            account_name=request.form.get('production_profile','')
            if action=='work' and account_name:
                from production_profiles import load
                account=load(root).get(account_name)
                if account is None or mode!='short': abort(400,'Choose a valid short production profile')
            if action=='work':
                try: limit=int(request.form.get('limit','10'))
                except ValueError: abort(400)
                if not 1<=limit<=100: abort(400)
                cmd+=['--limit',str(limit),'--out',str(out)]
                if (account['campaign'] if account else request.form.get('ads')=='1'):
                    if not campaigns.exists(): abort(400,'Create a campaign first')
                    cmd+=['--campaigns',str(campaigns)]
            env=os.environ.copy()
            for key in ('CLIP_PRODUCTION_PROFILE','CLIP_CAMPAIGN_NAME','CLIP_COVER_MODE','CLIP_COVER_TITLE','CLIP_COVER_COLOR'): env.pop(key,None)
            env['CLIP_CAPTIONS']='1' if request.form.get('captions')=='1' else '0'
            env['CLIP_SMART_SPEECH']='1' if request.form.get('smart_speech')=='1' else '0'
            layout=request.form.get('layout','circle')
            if layout not in ('circle','rectangle'): abort(400)
            env['CLIP_SHORT_LAYOUT']=layout
            background=assets/'short-background.jpg'
            if background.is_file(): env['CLIP_SHORT_BACKGROUND']=str(background)
            else: env.pop('CLIP_SHORT_BACKGROUND',None)
            env.pop('CLIP_SHORT_TEMPLATE',None)
            if action=='work' and (account or request.form.get('profile')):
                from short_templates import load,validate
                profiles=load(root)
                name=account['template'] if account else request.form['profile']
                if name not in profiles: abort(400,'Unknown template')
                spec=validate(profiles[name])
                env['CLIP_SHORT_TEMPLATE']=json.dumps(spec)
                if spec['background']:
                    path=assets/'backgrounds'/spec['background']
                    if not path.is_file(): abort(400,'Background missing')
                    env['CLIP_SHORT_BACKGROUND']=str(path)
                else: env.pop('CLIP_SHORT_BACKGROUND',None)
            if account:
                env['CLIP_COVER_MODE']=account.get('cover_mode','auto')
                env['CLIP_COVER_TITLE']=account.get('cover_title','') or account.get('handle','')
                env['CLIP_COVER_COLOR']=account.get('cover_color','#172536')
                env['CLIP_PRODUCTION_PROFILE']=account_name
                env['CLIP_CAPTIONS']='1' if account['captions'] else '0'
                env['CLIP_FONT_SIZE']=str(account['font_size'])
                env['CLIP_CAPTION_MARGIN']=str(account['caption_margin'])
                if account['campaign']: env['CLIP_CAMPAIGN_NAME']=account['campaign']
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
            return render_template('publishing.html',accounts=accounts,drafts=drafts,ready=ready,totals=totals,csrf=session['csrf'],publisher_running=publisher['process'] is not None and publisher['process'].poll() is None,profiles=__import__('production_profiles').load(root))
        finally: db.close()

    @app.post('/publishing/<action>')
    def publication_action(action):
        db=init(connect(dbpath))
        try:
            if action=='account':
                add_account(db,request.form['name'],request.form['platform'],request.form['destination'],
                    request.form['token_env'],request.form.get('topic',''),int(request.form.get('daily','2')))
            elif action=='configure':
                profile=request.form.get('profile','')
                if profile and profile not in __import__('production_profiles').load(root): raise ValueError('Unknown profile')
                configure_auto(db,int(request.form['id']),profile,request.form.get('caption',''),int(request.form.get('interval','3600')),request.form.get('auto')=='1')
            elif action=='sync': sync_ready(db)
            elif action=='toggle':
                with db: db.execute('UPDATE accounts SET enabled=1-enabled WHERE id=?',(int(request.form['id']),))
            elif action=='draft':
                enqueue(db,int(request.form['account']),int(request.form['clip']),request.form['caption'],int(request.form.get('scheduled') or time.time()))
            elif action=='approve':
                if not approve(db,int(request.form['id'])): abort(409)
            elif action=='measure':
                measure(db,int(request.form['id']),int(request.form['views']),int(request.form['accepted']),int(request.form['kopecks']))
            elif action=='stop':
                (root/'publication.stop').touch()
            elif action in ('send','run'):
                with lock:
                    if publisher['process'] and publisher['process'].poll() is None: abort(409,'Publisher already running')
                    (root/'publication.stop').unlink(missing_ok=True)
                    log=root/'publication-job.log'
                    with log.open('wb') as fp:
                        proc=subprocess.Popen([sys.executable,'-u',str(ROOT/'publishing.py'),'--root',str(root),action],cwd=root,stdout=fp,stderr=subprocess.STDOUT)
                    publisher['process']=proc
            else: abort(404)
        except (ValueError,KeyError,sqlite3.IntegrityError): abort(400,'Invalid publication settings')
        finally: db.close()
        return redirect(url_for('publication_page'))

    @app.get('/clips/<int:cid>/cover')
    def cover(cid):
        db=connect(dbpath)
        try: row=db.execute("SELECT cover FROM clips WHERE id=? AND status='done'",(cid,)).fetchone()
        finally: db.close()
        if not row or not row['cover']: abort(404)
        path=(root/row['cover']).resolve()
        if not path.is_relative_to(out.resolve()) or not path.is_file() or path.suffix!='.jpg': abort(404)
        return send_file(path,mimetype='image/jpeg',conditional=True)

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
