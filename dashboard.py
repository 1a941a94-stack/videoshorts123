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
    performance=root/'performance.json'
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

    next_trash_check=0

    @app.get('/healthz')
    def healthz():
        return jsonify(ok=True)

    @app.before_request
    def trash_maintenance():
        if request.endpoint=='healthz': return
        nonlocal next_trash_check
        if time.monotonic()<next_trash_check: return
        if not lock.acquire(blocking=False): return
        try:
            if time.monotonic()<next_trash_check: return
            if (job['process'] and job['process'].poll() is None) or preview_lock.locked(): return
            from filelock import FileLock,Timeout
            from storage_control import expire_trash
            try:
                with FileLock(str(dbpath)+'.production.lock',timeout=0):
                    db=connect(dbpath)
                    try: expire_trash(db,root)
                    finally: db.close()
                    next_trash_check=time.monotonic()+3600
            except Timeout: pass
            except (OSError,sqlite3.Error):
                app.logger.exception('Trash maintenance failed')
                next_trash_check=time.monotonic()+3600
        finally: lock.release()

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
            preview_active=preview_lock.locked()
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
        response=jsonify(running=running,preview_active=preview_active,result=result,action=action,elapsed=elapsed,log_age=age,
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
            status=request.args.get('clip_status','done')
            if status not in ('all','done','pending','running','failed','duplicate','ad_review','ad_rejected','archived'): status='all'
            query=request.args.get('q','').strip()[:150]
            page=max(1,min(100000,request.args.get('page',1,type=int)))
            where=[]; params=[]
            if status=='done': where.append("c.output IS NOT NULL AND c.status NOT IN ('archived','purged')")
            elif status!='all': where.append('c.status=?'); params.append(status)
            else: where.append("c.status NOT IN ('archived','purged')")
            batch_id=request.args.get('batch',type=int)
            if batch_id and batch_id>0: where.append('EXISTS (SELECT 1 FROM production_run_tasks rt WHERE rt.clip_id=c.id AND rt.run_id=? AND rt.status=\'done\')'); params.append(batch_id)
            if query: where.append("(instr(lower(coalesce(v.title,'')),lower(?))>0 OR cast(c.id as text)=?)"); params.extend([query,query.removeprefix('#')])
            clause=' WHERE '+' AND '.join(where) if where else ''
            base=' FROM clips c JOIN videos v ON v.id=c.video_id'+clause
            clip_count=db.execute('SELECT count(*)'+base,params).fetchone()[0]
            page=min(page,max(1,(clip_count+99)//100))
            clips=db.execute('SELECT c.*,v.title,v.url'+base+' ORDER BY c.updated DESC,c.id DESC LIMIT 100 OFFSET ?',(*params,(page-1)*100)).fetchall()
            stats=dict(db.execute('SELECT status,count(*) FROM clips GROUP BY status').fetchall())
            total=db.execute('SELECT count(*) FROM videos').fetchone()[0]
            from production_runs import summary
            from dispatcher import day_start
            latest=db.execute('SELECT id FROM production_runs ORDER BY id DESC LIMIT 1').fetchone()
            current_run=summary(db,latest['id']) if latest else None
            recent=db.execute("SELECT c.id,c.cover,c.actual_start,c.actual_end,c.run_id,v.title FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.status='done' AND c.output IS NOT NULL ORDER BY c.updated DESC,c.id DESC LIMIT 6").fetchall()
            today=db.execute("SELECT count(*) FROM clips WHERE status='done' AND updated>=?",(day_start(),)).fetchone()[0]
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
            clip_status=status,clip_query=query,clip_page=page,clip_count=clip_count,clip_batch=batch_id,
            run_configs=__import__('run_configs').load(root),current_run=current_run,recent=recent,today=today,
            benchmark=read_json(root/'benchmark-result.json',{}),encoder=read_json(performance,{}).get('encoder','cpu'),
            production_profiles=__import__('production_profiles').load(root),short_profiles=__import__('short_templates').load(root),backgrounds=sorted(p.name for p in (assets/'backgrounds').glob('*') if p.suffix.lower() in ('.jpg','.mp4','.webm','.mov','.gif')),ad_refs=sorted(p.stem for p in (assets/'ad-references').glob('*.png')),campaigns=read_json(campaigns,{'campaigns':[]})['campaigns'],settings={**DEFAULTS,**read_json(config,{})})

    @app.get('/business/reports')
    def business_reports():
        from business_reports import status
        db=connect(dbpath)
        try:
            data=status(db)
            db.commit()
        finally: db.close()
        return render_template('business_reports.html',data=data)

    def report_loop():
        from business_reports import tick
        from filelock import FileLock,Timeout
        while True:
            time.sleep(60)
            db=None
            try:
                if os.environ.get('CLIP_REPORT_ENABLED','0')!='1': continue
                with FileLock(str(root/'business-reports.lock'),timeout=0):
                    db=init(connect(dbpath))
                    tick(db,root)
            except Timeout: pass
            except Exception:
                # Do not log exception text: HTTP errors can contain the bot token.
                app.logger.warning('Business report check failed; inspect report configuration')
            finally:
                if db is not None: db.close()

    @app.get('/business/analytics')
    def business_analytics():
        from business_analytics import state,DIMENSIONS
        days=request.args.get('days',30,type=int)
        dimension=request.args.get('dimension','campaign')
        if days not in (0,7,30,90): days=30
        if dimension not in DIMENSIONS: dimension='campaign'
        db=init(connect(dbpath))
        try: data=state(db,days,dimension)
        finally: db.close()
        return render_template('business_analytics.html',data=data)

    @app.get('/business/finance')
    def business_finance():
        from business_finance import state
        days=request.args.get('days',30,type=int)
        if days not in (7,30,90): days=30
        db=init(connect(dbpath))
        try:
            data=state(db,days)
            db.commit()
        finally: db.close()
        return render_template('business_finance.html',data=data)

    @app.get('/business/monetization')
    def business_monetization():
        from business_monetization import state,campaigns
        db=init(connect(dbpath))
        try:
            data=state(db)
            db.commit()
        finally: db.close()
        return render_template('business_monetization.html',data=data,campaigns=campaigns(root),csrf=session['csrf'],error=request.args.get('error',''),message=request.args.get('message',''))

    @app.post('/business/monetization/<operation>')
    def business_monetization_action(operation):
        from business_monetization import partner,terms,payout
        from business_factory import init as init_business,event
        if operation not in ('partner','terms','payout'): abort(404)
        db=init(connect(dbpath))
        try:
            if operation=='partner': partner(db,request.form)
            elif operation=='terms': terms(db,root,request.form)
            else: payout(db,request.form)
            with db:
                init_business(db)
                event(db,'monetization',{'partner':'Добавлен рекламный партнёр','terms':'Сохранены условия кампании','payout':'Учтена полученная выплата'}[operation])
            return redirect(url_for('business_monetization',message='Сохранено'),code=303)
        except (ValueError,KeyError,sqlite3.IntegrityError) as exc:
            return redirect(url_for('business_monetization',error='Повторная запись' if isinstance(exc,sqlite3.IntegrityError) else str(exc)),code=303)
        finally: db.close()

    @app.get('/business/calendar')
    def business_calendar():
        from business_calendar import calendar
        days=request.args.get('days',7,type=int)
        if days not in (1,7,30): days=7
        aid=request.args.get('account',type=int)
        db=init(connect(dbpath))
        try:
            data=calendar(db,days,aid)
            db.commit()
        finally: db.close()
        return render_template('business_calendar.html',data=data,days=days,aid=aid,csrf=session['csrf'],error=request.args.get('error',''),message=request.args.get('message',''))

    @app.post('/business/calendar/draft')
    def business_calendar_draft():
        from business_calendar import create_draft,parse_date
        db=init(connect(dbpath))
        try:
            pid=create_draft(db,int(request.form['account']),int(request.form['clip']),int(request.form.get('material') or 0),parse_date(request.form['scheduled']),request.form.get('caption',''))
            return redirect(url_for('business_calendar',message=f'Создан черновик #{pid}'),code=303)
        except (ValueError,KeyError,sqlite3.IntegrityError) as exc:
            return redirect(url_for('business_calendar',error=str(exc)),code=303)
        finally: db.close()

    @app.post('/business/calendar/<int:pid>/<operation>')
    def business_calendar_modify(pid,operation):
        from business_calendar import modify,parse_date
        db=init(connect(dbpath))
        try:
            modify(db,pid,operation,parse_date(request.form.get('scheduled','')) if operation=='move' else None)
            return redirect(url_for('business_calendar',message='Изменения сохранены'),code=303)
        except ValueError as exc:
            return redirect(url_for('business_calendar',error=str(exc)),code=303)
        finally: db.close()

    @app.get('/business/resources')
    def business_resources():
        from business_resources import state
        db=connect(dbpath)
        try:
            data=state(db)
            from proxy6_inventory import state as proxy_state
            data['proxy6']=proxy_state(db)
            db.commit()
        finally: db.close()
        return render_template('business_resources.html',data=data,csrf=session['csrf'],message=request.args.get('message',''),error=request.args.get('error',''))

    @app.post('/business/resources/proxy6-sync')
    def proxy6_sync():
        from proxy6_inventory import refresh
        db=connect(dbpath)
        try:
            count=refresh(db)
            return redirect(url_for('business_resources',message=f'PROXY6: синхронизировано {count} услуг'),code=303)
        except ValueError as exc:
            return redirect(url_for('business_resources',error=str(exc)),code=303)
        finally: db.close()

    @app.post('/business/resources/proxy6-quote')
    def proxy6_quote():
        from proxy6_inventory import quote
        try:
            price,currency=quote(int(request.form.get('count','')),int(request.form.get('period','')),int(request.form.get('version','')))
            return redirect(url_for('business_resources',message=f'Стоимость PROXY6: {price} {currency}'),code=303)
        except ValueError as exc:
            return redirect(url_for('business_resources',error=str(exc)),code=303)

    @app.post('/business/resources/proxy6-invoice')
    def proxy6_invoice():
        from business_resources import record_proxy6_invoice
        db=connect(dbpath)
        try:
            added=record_proxy6_invoice(db,request.form)
            return redirect(url_for('business_resources',message='Расход учтён' if added else 'Счёт уже учтён'),code=303)
        except (ValueError,sqlite3.IntegrityError) as exc:
            return redirect(url_for('business_resources',error=str(exc)),code=303)
        finally: db.close()

    @app.post('/business/resources/<operation>')
    def business_resource_action(operation):
        from business_resources import add,budget,record,archive
        from business_factory import init as init_business,event
        if operation not in ('add','budget','record','archive'): abort(404)
        db=connect(dbpath)
        try:
            if operation=='add': add(db,request.form)
            elif operation=='budget': budget(db,request.form)
            elif operation=='record': record(db,request.form)
            else: archive(db,int(request.form.get('id','')))
            with db:
                init_business(db)
                event(db,'resources',{'add':'Добавлена услуга','budget':'Обновлён бюджет','record':'Учтён фактический расход','archive':'Услуга архивирована'}[operation])
            return redirect(url_for('business_resources',message='Сохранено'),code=303)
        except (ValueError,sqlite3.IntegrityError) as exc:
            return redirect(url_for('business_resources',error='Дублирующаяся запись' if isinstance(exc,sqlite3.IntegrityError) else str(exc)),code=303)
        finally: db.close()

    @app.get('/business/accounts')
    def business_accounts():
        from business_accounts import init as init_accounts,rows
        db=init(connect(dbpath))
        try:
            init_accounts(db)
            total=db.execute('SELECT count(*) FROM accounts').fetchone()[0]
            page=min(max(1,request.args.get('page',1,type=int)),max(1,(total+99)//100))
            accounts=rows(db,offset=(page-1)*100)
            from account_lifecycle import decorate
            decorate(db,accounts)
            from account_sessions import describe,instructions
            for account in accounts:
                account['session_status']=describe(root,account)
                account['session_instructions']=instructions(account)
                account.pop('token_env',None)
                account['profile']=json.loads(account.pop('profile_payload') or '{}')
            db.commit()
        finally: db.close()
        return render_template('business_accounts.html',accounts=accounts,total=total,page=page,csrf=session['csrf'],message=request.args.get('message',''),error=request.args.get('error',''))

    @app.post('/business/accounts/import')
    def business_accounts_import():
        from business_accounts import import_csv
        from business_factory import init as init_business,event
        db=init(connect(dbpath))
        try:
            upload=request.files.get('file')
            if not upload: raise ValueError('Выберите CSV')
            added,duplicates=import_csv(db,upload.stream.read(2*1024*1024+1))
            with db:
                init_business(db)
                event(db,'accounts',f'Импорт аккаунтов: {added}, дубли: {duplicates}')
            return redirect(url_for('business_accounts',message=f'Добавлено: {added}. Дубликатов: {duplicates}.'),code=303)
        except (ValueError,sqlite3.IntegrityError) as exc:
            return redirect(url_for('business_accounts',error=str(exc)),code=303)
        finally: db.close()

    @app.post('/business/accounts/<int:aid>/lifecycle')
    def business_account_lifecycle(aid):
        from account_lifecycle import change
        from datetime import datetime,timezone
        db=init(connect(dbpath))
        try:
            operation=request.form.get('operation','')
            start=None
            if operation=='schedule':
                start=int(datetime.strptime(request.form.get('start_at',''),'%Y-%m-%dT%H:%M').replace(tzinfo=timezone.utc).timestamp())
            change(db,aid,operation,start)
            return redirect(url_for('business_accounts',message='Состояние сохранено'),code=303)
        except ValueError as exc:
            return redirect(url_for('business_accounts',error=str(exc)),code=303)
        finally: db.close()

    @app.post('/business/accounts/<int:aid>/<operation>')
    def business_account_action(aid,operation):
        from business_accounts import assign,release
        from business_factory import init as init_business,event
        if operation not in ('assign','release','pause'): abort(404)
        db=init(connect(dbpath))
        try:
            if operation=='assign': assign(db,aid)
            elif operation=='release': release(db,aid)
            else:
                with db:
                    if not db.execute('UPDATE accounts SET enabled=0 WHERE id=?',(aid,)).rowcount: raise ValueError('Аккаунт не найден')
            with db:
                init_business(db)
                event(db,'accounts',f'Аккаунт #{aid}: '+{'assign':'материалы зарезервированы','release':'резерв освобождён','pause':'новые публикации приостановлены'}[operation])
            return redirect(url_for('business_accounts',message='Операция выполнена'),code=303)
        except ValueError as exc:
            return redirect(url_for('business_accounts',error=str(exc)),code=303)
        finally: db.close()

    @app.get('/business/library')
    def business_library():
        from business_library import init,inventory,KINDS
        kind=request.args.get('kind','avatar')
        if kind not in KINDS: abort(400)
        cat=request.args.get('category','')[:80]
        status=request.args.get('status','all')
        if status not in ('all','free','reserved','used','archived'): abort(400)
        page=max(1,request.args.get('page',1,type=int))
        db=connect(dbpath)
        try:
            init(db)
            counts=inventory(db)
            where='kind=?'; args=[kind]
            if cat: where+=' AND category=?'; args.append(cat)
            if status!='all': where+=' AND status=?'; args.append(status)
            total=db.execute('SELECT count(*) FROM business_materials WHERE '+where,args).fetchone()[0]
            page=min(page,max(1,(total+49)//50))
            rows=[{**dict(row),'payload':json.loads(row['payload'])} for row in db.execute('SELECT * FROM business_materials WHERE '+where+' ORDER BY id DESC LIMIT 50 OFFSET ?',(*args,(page-1)*50))]
            categories=[x[0] for x in db.execute('SELECT DISTINCT category FROM business_materials WHERE kind=? ORDER BY category',(kind,))]
            db.commit()
        finally: db.close()
        return render_template('business_library.html',rows=rows,counts=counts,kind=kind,category=cat,categories=categories,status=status,page=page,total=total,csrf=session['csrf'],message=request.args.get('message',''),error=request.args.get('error',''))

    @app.post('/business/library/import')
    def business_library_import():
        from business_library import import_text,import_images
        from business_factory import init as init_business,event
        kind=request.form.get('kind','')
        db=connect(dbpath)
        try:
            with lock:
                if kind=='avatar':
                    added,duplicates=import_images(db,root,request.files.getlist('files'),request.form.get('category',''))
                else:
                    upload=request.files.get('file')
                    if not upload: raise ValueError('Выберите TXT')
                    added,duplicates=import_text(db,upload.stream.read(2*1024*1024+1),kind)
                with db:
                    init_business(db)
                    event(db,'library',f'Импорт {kind}: добавлено {added}, дубли {duplicates}')
            return redirect(url_for('business_library',kind=kind,message=f'Добавлено: {added}. Дубликатов: {duplicates}.'),code=303)
        except (ValueError,OSError) as exc:
            return redirect(url_for('business_library',kind=kind if kind in ('avatar','profile','caption') else 'avatar',error=str(exc)),code=303)
        finally: db.close()

    @app.post('/business/library/<int:mid>/archive')
    def business_library_archive(mid):
        from business_library import init,archive
        db=connect(dbpath)
        try:
            init(db)
            row=db.execute('SELECT kind FROM business_materials WHERE id=?',(mid,)).fetchone()
            if not row: abort(404)
            if not archive(db,mid,request.form.get('restore')=='1'): abort(409,'Материал занят или уже использован')
            return redirect(url_for('business_library',kind=row['kind']),code=303)
        finally: db.close()

    @app.get('/business/library/avatar/<int:mid>')
    def business_avatar(mid):
        from business_library import init
        db=connect(dbpath)
        try:
            init(db)
            row=db.execute("SELECT payload FROM business_materials WHERE id=? AND kind='avatar'",(mid,)).fetchone()
        finally: db.close()
        if not row: abort(404)
        folder=(assets/'business-avatars').resolve()
        path=(folder/json.loads(row['payload'])['file']).resolve()
        if not path.is_relative_to(folder) or not path.is_file(): abort(404)
        return send_file(path,mimetype='image/png',conditional=True)

    @app.get('/business')
    def business():
        from business_factory import state
        from run_configs import load
        db=connect(dbpath)
        try:
            init(db)
            configs=load(root)['items']
            data=state(db,configs)
            db.commit()
        finally: db.close()
        return render_template('business.html',data=data,configs=configs,csrf=session['csrf'],error=request.args.get('error',''))

    @app.post('/business/settings')
    def business_settings():
        from business_factory import save
        from run_configs import load
        db=connect(dbpath)
        try:
            save(db,request.form,load(root)['items'])
        except (ValueError,KeyError) as exc:
            return redirect(url_for('business',error=str(exc)),code=303)
        finally: db.close()
        return redirect(url_for('business'),code=303)

    @app.post('/business/controller/<operation>')
    def business_controller_action(operation):
        from factory_controller import enable,state
        if operation not in ('start','stop'): abort(404)
        with lock:
            db=connect(dbpath)
            try:
                enable(db,operation=='start')
                current=state(db)
                if operation=='start':
                    (root/'publication.stop').unlink(missing_ok=True)
                if operation=='stop':
                    (root/'publication.stop').touch()
                    if current['run_id'] is not None:
                        active=db.execute("SELECT 1 FROM production_runs WHERE id=? AND status IN ('queued','running')",(current['run_id'],)).fetchone()
                        if active and (job.get('run_id')==current['run_id'] or not (job['process'] and job['process'].poll() is None)):
                            (root/'factory.stop').touch()
                db.commit()
            finally: db.close()
        return redirect(url_for('business'),code=303)

    def controller_loop():
        from factory_controller import state,decision,record,interrupted_run
        from run_configs import load
        from production_runs import create,set_status
        from filelock import FileLock,Timeout
        while True:
            time.sleep(5)
            if not lock.acquire(blocking=False): continue
            db=None
            try:
                db=init(connect(dbpath))
                current=state(db)
                db.commit()
                if not current['enabled'] or current['next_check']>time.time(): continue
                from business_resources import state as resource_state
                allowed=not any(resource_state(db)['over'])
                db.commit()
                if allowed and not (root/'publication.stop').exists() and not (publisher['process'] and publisher['process'].poll() is None):
                    due=db.execute("SELECT 1 FROM publications WHERE status='approved' AND scheduled<=? LIMIT 1",(int(time.time()),)).fetchone()
                    if due:
                        try:
                            with FileLock(str(root/'publication.lock'),timeout=0):
                                pass
                        except Timeout:
                            pass
                        else:
                            with (root/'publication-job.log').open('ab') as fp:
                                publisher['process']=subprocess.Popen([sys.executable,'-u',str(ROOT/'publishing.py'),'--root',str(root),'factory-send'],cwd=root,stdout=fp,stderr=subprocess.STDOUT)
                if (job['process'] and job['process'].poll() is None) or preview_lock.locked():
                    record(db,'Производство занято',30)
                    continue
                with FileLock(str(dbpath)+'.production.lock',timeout=0):
                    # Plan opted-in publications locally; this never sends media.
                    # The separate publisher retains its own explicit start/stop.
                    from business_resources import state as resource_state
                    if not any(resource_state(db)['over']):
                        db.commit()
                        queued=sync_ready(db)
                        if queued:
                            from business_factory import event
                            with db: event(db,'publication',f'Запланировано публикаций: {queued}')
                    else:
                        db.commit()
                    recovery=interrupted_run(db,root,current)
                    if recovery:
                        from diagnostics import readiness
                        import shutil
                        issues=[x['name'] for x in readiness(root,recovery['mode']) if x['required'] and not x['ok']]
                        if not allowed or issues or shutil.disk_usage(root).free<3*1024**3:
                            record(db,'Восстановление партии ожидает готовности ресурсов',300)
                            continue
                        run_id=recovery['id']
                        record(db,f'Восстановление прерванной партии #{run_id}',60,run_id)
                    else:
                        task,detail,delay=decision(db,root,load(root)['items'])
                        db.commit()
                        if not task:
                            record(db,detail,delay)
                            continue
                        goal,snap=task
                        run_id=create(db,goal,snap)
                        record(db,f'Запуск партии #{run_id}: до {goal} роликов',60,run_id)
                try: launch_run(run_id)
                except OSError as exc:
                    set_status(db,run_id,'failed',str(exc))
                    record(db,'Не удалось запустить производство',300)
            except Timeout:
                if db is not None: record(db,'Производство занято другим процессом',60)
            except Exception:
                app.logger.exception('Factory controller check failed')
                if db is not None:
                    try:
                        db.rollback()
                        record(db,'Ошибка проверки; повтор через 5 минут',300)
                    except Exception: app.logger.exception('Cannot record controller error')
            finally:
                if db is not None: db.close()
                lock.release()

    @app.post('/business/start')
    def business_start():
        from business_factory import state,event
        from run_configs import load,resolve
        from production_runs import create,set_status
        from diagnostics import readiness
        from filelock import FileLock,Timeout
        with lock:
            if (job['process'] and job['process'].poll() is None) or preview_lock.locked():
                return redirect(url_for('business',error='Производство уже занято'),code=303)
            db=connect(dbpath)
            try:
                init(db)
                configs=load(root)['items']
                data=state(db,configs)
                if not data['configured']: raise ValueError('Сохраните настройки завода')
                if not data['missing']: raise ValueError('Целевой запас уже заполнен')
                item=configs[data['config']['configuration']]
                if not data['pending'] and (not item['auto_search'] or not data['sources']):
                    raise ValueError('Добавьте исходники или включите поиск в конфигурации')
                issues=[x['name'] for x in readiness(root,item['mode']) if x['required'] and not x['ok']]
                if issues: raise ValueError('Не готова система: '+', '.join(issues))
                snap=resolve(root,item)
                snap['name']='Бизнес-завод: '+data['config']['configuration']
                with FileLock(str(dbpath)+'.production.lock',timeout=0):
                    run_id=create(db,min(1000,data['missing']),snap)
                    with db: event(db,'production','Запрошена партия #'+str(run_id))
                try: launch_run(run_id)
                except OSError as exc:
                    set_status(db,run_id,'failed',str(exc))
                    raise
            except (ValueError,KeyError,OSError,Timeout) as exc:
                return redirect(url_for('business',error=str(exc)),code=303)
            finally: db.close()
        return redirect(url_for('business'),code=303)

    @app.get('/api/queue')
    def queue_state():
        from queue_control import explain
        db=connect(dbpath)
        try:
            rows=db.execute("""SELECT c.*,v.title,v.url FROM clips c JOIN videos v ON v.id=c.video_id
                WHERE c.status IN ('pending','running','failed','ad_review','duplicate','ad_rejected','cancelled')
                ORDER BY CASE c.status WHEN 'running' THEN 0 WHEN 'failed' THEN 1 WHEN 'ad_review' THEN 1 WHEN 'pending' THEN 2 ELSE 3 END,c.priority DESC,c.id DESC LIMIT 500""").fetchall()
            items=[]
            for row in rows:
                item={k:row[k] for k in ('id','title','status','priority','attempts','error','ad_result','run_id','mode')}
                item['source']='Локальный файл' if row['video_id'].startswith('local_') else 'Telegram' if row['video_id'].startswith('tg_') else 'YouTube'
                item['issue']=explain(row)
                item['can_retry']=bool(row['task_snapshot']) and item['issue']['retry']
                items.append(item)
            counts=dict(db.execute('SELECT status,count(*) FROM clips GROUP BY status'))
            return jsonify(items=items,counts=counts)
        finally: db.close()

    @app.post('/queue/clear')
    def queue_clear():
        from filelock import FileLock,Timeout
        if request.form.get('confirm')!='1': abort(400,'Подтвердите очистку')
        with lock:
            if (job['process'] and job['process'].poll() is None) or preview_lock.locked():
                return redirect(url_for('index',clear_busy=1)+'#queue',code=303)
            try:
                with FileLock(str(dbpath)+'.production.lock',timeout=0):
                    db=connect(dbpath)
                    try:
                        from queue_control import clear_discovered
                        removed=clear_discovered(db)
                    finally: db.close()
            except Timeout:
                return redirect(url_for('index',clear_busy=1)+'#queue',code=303)
        return redirect(url_for('index',queue_removed=removed)+'#queue',code=303)

    @app.post('/sources/clear-active')
    def clear_active_sources():
        from filelock import FileLock,Timeout
        if request.form.get('confirm')!='1': abort(400,'Подтвердите удаление')
        with lock:
            if (job['process'] and job['process'].poll() is None) or preview_lock.locked():
                return redirect(url_for('index',clear_busy=1)+'#telegram',code=303)
            try:
                with FileLock(str(dbpath)+'.production.lock',timeout=0):
                    db=connect(dbpath)
                    try:
                        with db:
                            n=db.execute('DELETE FROM sources WHERE enabled=1').rowcount
                            n+=db.execute('DELETE FROM telegram_channels WHERE enabled=1').rowcount
                    finally: db.close()
            except Timeout:
                return redirect(url_for('index',clear_busy=1)+'#telegram',code=303)
        return redirect(url_for('index',sources_removed=n)+'#telegram',code=303)

    @app.post('/queue/<int:cid>/<operation>')
    def queue_manage(cid,operation):
        from queue_control import retry_task,queue_action
        from filelock import FileLock,Timeout
        with lock:
            if (job['process'] and job['process'].poll() is None) or preview_lock.locked(): abort(409,'Приостановите производство')
            db=connect(dbpath)
            try:
                with FileLock(str(dbpath)+'.production.lock',timeout=0):
                    if operation=='retry': run_id=retry_task(db,cid)
                    else: queue_action(db,cid,operation)
                if operation=='retry': launch_run(run_id)
            except (ValueError,Timeout,OSError) as exc: abort(400,str(exc))
            finally: db.close()
        return redirect(url_for('index')+'#queue')

    @app.get('/api/diagnostics')
    def diagnostics_state():
        from diagnostics import readiness
        mode=request.args.get('mode','short')
        if mode not in ('short','long'): abort(400)
        return jsonify(checks=readiness(root,mode))

    @app.get('/api/storage')
    def storage_state():
        from storage_control import stats
        db=connect(dbpath)
        try: return jsonify(stats(root,db))
        finally: db.close()

    @app.post('/storage/clear-cache')
    def storage_clear():
        from storage_control import clear_cache
        from filelock import FileLock,Timeout
        with lock:
            if (job['process'] and job['process'].poll() is None) or preview_lock.locked(): abort(409,'Остановите производство')
            try:
                with FileLock(str(dbpath)+'.production.lock',timeout=0): clear_cache(root)
            except (Timeout,ValueError,OSError) as exc: abort(409,str(exc))
        return redirect(url_for('index')+'#storage')

    @app.get('/api/production')
    def production_state():
        from production_runs import summary
        from run_configs import load
        db=connect(dbpath)
        try:
            rows=db.execute('SELECT id FROM production_runs ORDER BY id DESC LIMIT 30').fetchall()
            runs=[summary(db,r['id']) for r in rows]
            for run in runs:
                run['name']=run['snapshot'].get('name','Производственная партия')
                run.pop('snapshot',None)
            from dispatcher import day_start
            today=db.execute("SELECT count(*) FROM clips WHERE status='done' AND updated>=?",(day_start(),)).fetchone()[0]
            stats=dict(db.execute('SELECT status,count(*) FROM clips GROUP BY status'))
            recent=[dict(r) for r in db.execute("SELECT c.id,c.cover,c.actual_start,c.actual_end,c.run_id,v.title FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.status='done' AND c.output IS NOT NULL ORDER BY c.updated DESC,c.id DESC LIMIT 6")]
            active_id=job.get('run_id') if job['action']=='run-batch' and job['process'] and job['process'].poll() is None else None
            return jsonify(configurations=load(root),runs=runs,today=today,stats=stats,recent=recent,active_id=active_id)
        finally: db.close()

    @app.post('/run-configs')
    def manage_config():
        from run_configs import save,load,write
        with lock:
            try:
                op=request.form.get('operation','save')
                if op=='save': save(root,request.form)
                elif op in ('copy','delete'):
                    data=load(root)
                    name=request.form['name']
                    if name not in data['items']: abort(404)
                    if op=='copy':
                        target=request.form.get('target','').strip()
                        if not 1<=len(target)<=80 or target in data['items'] or len(data['items'])>=100: raise ValueError('Invalid new name')
                        data['items'][target]=dict(data['items'][name])
                        data['last']=target
                    else:
                        del data['items'][name]
                        if data['last']==name: data['last']=next(iter(data['items']),'')
                    write(root,data)
                else: abort(400)
            except (ValueError,KeyError,OSError) as exc: abort(400,str(exc))
        return redirect(url_for('index')+'#production-runs')

    def launch_run(run_id):
        cmd=[sys.executable,'-u',str(ROOT/'pipeline.py'),'--db',str(dbpath)]
        if config.exists(): cmd+=['--config',str(config)]
        cmd+=['run-batch',str(run_id),'--out',str(out)]
        (root/'factory.stop').unlink(missing_ok=True)
        log=root/'dashboard-job.log'
        with log.open('wb') as fp:
            proc=subprocess.Popen(cmd,cwd=root,stdout=fp,stderr=subprocess.STDOUT)
        job.update(process=proc,action='run-batch',run_id=run_id,log=log,started=time.time(),finished=None)

    @app.post('/production/start')
    def production_start():
        from run_configs import load,resolve,write
        from production_runs import create,set_status
        with lock:
            if job['process'] and job['process'].poll() is None:
                return redirect(url_for('index',production_busy=job['action'] or 'job')+'#production-runs',code=303)
            if preview_lock.locked():
                return redirect(url_for('index',production_busy='preview')+'#production-runs',code=303)
            data=load(root)
            name=request.form.get('configuration','')
            try:
                item=data['items'][name]
                goal=int(request.form.get('goal') or item['goal'])
                snap=resolve(root,item)
                from diagnostics import readiness
                issues=[x['name'] for x in readiness(root,item['mode']) if x['required'] and not x['ok']]
                if issues: abort(409,'Не готова система: '+', '.join(issues))
                snap['name']=name
                db=connect(dbpath)
                try: run_id=create(db,goal,snap)
                finally: db.close()
                data['last']=name
                write(root,data)
                try: launch_run(run_id)
                except OSError as exc:
                    db=connect(dbpath)
                    try: set_status(db,run_id,'failed',str(exc))
                    finally: db.close()
                    raise
            except (ValueError,KeyError,OSError) as exc: abort(400,str(exc))
        return redirect(url_for('index')+'#production-runs')

    @app.post('/production/<int:run_id>/pause')
    def production_pause(run_id):
        with lock:
            if job['action']!='run-batch' or job.get('run_id')!=run_id or not job['process'] or job['process'].poll() is not None: abort(409)
            (root/'factory.stop').touch()
        return redirect(url_for('index')+'#production-runs')

    @app.post('/production/<int:run_id>/resume')
    def production_resume(run_id):
        from production_runs import summary
        with lock:
            if (job['process'] and job['process'].poll() is None) or preview_lock.locked(): abort(409)
            db=connect(dbpath)
            try:
                batch=summary(db,run_id)
                if batch['status'] not in ('paused','queued','running'): abort(409)
                from diagnostics import readiness
                issues=[x['name'] for x in readiness(root,batch['mode']) if x['required'] and not x['ok']]
                if issues: abort(409,'Не готова система: '+', '.join(issues))
            except ValueError: abort(404)
            finally: db.close()
            launch_run(run_id)
        return redirect(url_for('index')+'#production-runs')

    @app.post('/performance')
    def save_performance():
        mode=request.form.get('encoder','cpu')
        if mode not in ('cpu','auto','qsv'): abort(400)
        with lock: save_json(performance,{'encoder':mode})
        return redirect(url_for('index')+'#performance')

    @app.post('/performance/benchmark')
    def start_benchmark():
        with lock:
            if job['process'] and job['process'].poll() is None: abort(409,'Production job already running')
            if preview_lock.locked(): abort(409,'Preview already running')
            log=root/'dashboard-job.log'
            with log.open('wb') as fp:
                proc=subprocess.Popen([sys.executable,'-u',str(ROOT/'benchmark.py'),'--root',str(root)],cwd=root,stdout=fp,stderr=subprocess.STDOUT)
            job.update(process=proc,action='benchmark',log=log,started=time.time(),finished=None)
        return redirect(url_for('index')+'#performance')

    @app.get('/api/telegram/proxy')
    def telegram_proxy_state():
        from telegram_proxy import load
        data=load(root)
        data['has_password']=bool(data.pop('password',''))
        return jsonify(data)

    @app.post('/telegram/proxy')
    def telegram_proxy_save():
        from telegram_proxy import save
        with lock:
            if job['process'] and job['process'].poll() is None: return jsonify(error='Остановите текущую задачу'),409
            try:
                save(root,request.form)
            except (ValueError,OSError) as exc: return jsonify(error=str(exc)),400
        return jsonify(ok=True)

    @app.post('/telegram/proxy/check')
    def telegram_proxy_check():
        from telegram_proxy import check
        try:
            check(root)
        except ValueError as exc: return jsonify(error=str(exc)),400
        except Exception as exc: return jsonify(error='Подключение не удалось: '+type(exc).__name__),502
        return jsonify(ok=True,transport=True)

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

    @app.post('/sources/<int:sid>/delete')
    def delete_source(sid):
        db=connect(dbpath)
        try:
            with db: db.execute('DELETE FROM sources WHERE id=?',(sid,))
        finally: db.close()
        return redirect(url_for('index')+'#sources')

    @app.post('/telegram/channels/<name>/delete')
    def delete_channel(name):
        db=connect(dbpath)
        try:
            with db: db.execute('DELETE FROM telegram_channels WHERE name=?',(name,))
        finally: db.close()
        return redirect(url_for('index')+'#telegram')

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

    @app.post('/local-import')
    def local_import():
        import tempfile
        from local_import import import_file,EXTENSIONS
        uploads=request.files.getlist('videos')
        if not 1<=len(uploads)<=50: abort(400,'Upload 1–50 videos per request')
        results=[]
        db=connect(dbpath)
        try:
            with tempfile.TemporaryDirectory() as folder:
                for i,upload in enumerate(uploads):
                    name=Path((upload.filename or '').replace('\\','/')).name
                    suffix=Path(name).suffix.lower()
                    if suffix not in EXTENSIONS:
                        results.append({'name':name,'status':'error','detail':'Unsupported extension'})
                        continue
                    path=Path(folder)/(str(i)+suffix)
                    try:
                        upload.save(path)
                        results.append({'name':name,'status':import_file(db,root,path,title=name)})
                    except (ValueError,KeyError,OSError,subprocess.SubprocessError,sqlite3.Error) as exc:
                        results.append({'name':name,'status':'error','detail':str(exc)[:200]})
                    finally: path.unlink(missing_ok=True)
        finally: db.close()
        return jsonify(results=results)

    @app.post('/short-preview')
    def short_preview():
        import tempfile
        from io import BytesIO
        from short_templates import validate
        from short_media import render_short
        from quality import inspect,verify
        from banners import choose
        with lock:
            if job['process'] and job['process'].poll() is None: abort(409,'Stop production before preview')
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
                import math
                raw_duration=float(meta['format']['duration'])
                if not math.isfinite(raw_duration): abort(400,'Invalid source duration')
                duration=min(5,raw_duration)
                if not .5<=duration<=5: abort(400,'Source must contain at least 0.5 seconds')
                name=request.form.get('preview_campaign','')
                banner=choose(campaigns,duration,campaign=name) if name else None
                from caption_style import from_form
                render_short(source,duration,result,banner,template=spec,background_path=background,captions=request.form.get('preview_captions')=='1',caption_style=from_form(request.form))
                verify(result,duration,any(s.get('codec_type')=='audio' for s in streams))
                from banners import overlap_warning
                if banner and spec.get('ad_layout'):
                    from dataclasses import replace
                    banner=replace(banner,position='center',margin=0,**spec['ad_layout'])
                response=send_file(BytesIO(result.read_bytes()),mimetype='video/mp4',download_name='preview.mp4',max_age=0)
                response.headers['X-Banner-Overlap']='1' if overlap_warning(banner,spec) else '0'
                return response
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
        return redirect(url_for('index')+'#media-library')

    @app.post('/short-backgrounds/<name>/delete')
    def delete_background(name):
        import re
        if not re.fullmatch(r'[a-f0-9]{24}\.(?:jpg|mp4|webm|mov|gif)',name): abort(404)
        with lock:
            if job['process'] and job['process'].poll() is None or preview_lock.locked(): abort(409,'Остановите монтаж')
            if any(p.get('background')==name for p in __import__('short_templates').load(root).values()): abort(409,'Фон используется шаблоном')
            db=connect(dbpath)
            try:
                if db.execute("SELECT 1 FROM clips WHERE instr(coalesce(task_snapshot,''),?)>0 LIMIT 1",(name,)).fetchone() or db.execute("SELECT 1 FROM production_runs WHERE instr(snapshot,?)>0 LIMIT 1",(name,)).fetchone(): abort(409,'Фон используется сохранённой задачей')
                (assets/'backgrounds'/name).unlink(missing_ok=True)
            finally: db.close()
        return redirect(url_for('index')+'#media-library')

    @app.post('/short-profiles/<name>/delete')
    def delete_template(name):
        with lock:
            if any(x.get('template')==name for x in __import__('run_configs').load(root)['items'].values()) or any(x.get('template')==name for x in __import__('production_profiles').load(root).values()): abort(409,'Шаблон используется конфигурацией')
            path=root/'short-templates.json'
            data=read_json(path,{})
            if name not in data: abort(404)
            del data[name]
            save_json(path,data)
        return redirect(url_for('index')+'#saved-templates')

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
                start=float(request.form['start']),end=float(request.form['end']) if request.form.get('end') else None,
                x=int(request.form.get('x',0)),y=int(request.form.get('y',0)))
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

    @app.post('/campaigns/<int:cid>/edit')
    def edit_campaign(cid):
        import math
        with lock:
            data=read_json(campaigns,{'campaigns':[]})
            if not 0<=cid<len(data['campaigns']): abort(404)
            row=data['campaigns'][cid]
            try:
                path=(root/row['path']).resolve()
                if not path.is_relative_to(assets.resolve()): raise ValueError('Invalid asset')
                spec=Banner(path,name=row['name'],width=int(request.form['width']),height=int(request.form['height']),
                    position=request.form['position'],margin=int(request.form['margin']),opacity=float(request.form['opacity']),
                    start=float(request.form['start']),end=float(request.form['end']) if request.form.get('end') else None,
                    x=int(request.form.get('x',0)),y=int(request.form.get('y',0)))
                weight=float(request.form['weight'])
                if not math.isfinite(weight) or not 0<weight<=100: raise ValueError('Invalid weight')
                row.update({k:v for k,v in vars(spec).items() if k!='path'},weight=weight)
                save_json(campaigns,data)
            except (ValueError,KeyError,OSError) as exc: abort(400,str(exc))
        return redirect(url_for('index')+'#campaigns')

    @app.get('/campaigns/<int:cid>/media')
    def campaign_media(cid):
        data=read_json(campaigns,{'campaigns':[]})
        if not 0<=cid<len(data['campaigns']): abort(404)
        path=(root/data['campaigns'][cid]['path']).resolve()
        if not path.is_relative_to(assets.resolve()) or not path.is_file(): abort(404)
        return send_file(path,conditional=True)

    @app.post('/campaigns/<int:cid>/archive')
    def archive_campaign(cid):
        with lock:
            data=read_json(campaigns,{'campaigns':[]})
            if not 0<=cid<len(data['campaigns']): abort(404)
            row=data['campaigns'][cid]
            row.update(enabled=False,archived=True)
            save_json(campaigns,data)
        return redirect(url_for('index')+'#campaigns')

    @app.post('/campaigns/<int:cid>/toggle')
    def toggle_campaign(cid):
        with lock:
            data=read_json(campaigns,{'campaigns':[]})
            if not 0<=cid<len(data['campaigns']): abort(404)
            row=data['campaigns'][cid]
            row['enabled']=not row.get('enabled',True)
            if row['enabled']: row['archived']=False
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
            if preview_lock.locked(): abort(409,'Preview already running')
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
            env['CLIP_ENCODER']=read_json(performance,{}).get('encoder','cpu')
            env.pop('CLIP_CAPTION_STYLE',None)
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
                from caption_style import from_account
                env['CLIP_CAPTION_STYLE']=json.dumps(from_account(account))
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
                with db: db.execute("UPDATE accounts SET enabled=1-enabled WHERE id=? AND NOT EXISTS(SELECT 1 FROM account_lifecycle l WHERE l.account_id=accounts.id AND l.state='archived')",(int(request.form['id']),))
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

    @app.get('/api/clips/<int:cid>/edit')
    def clip_edit_settings(cid):
        from remontage import settings
        db=connect(dbpath)
        try:
            row=db.execute('SELECT * FROM clips WHERE id=?',(cid,)).fetchone()
            if not row or row['mode']!='short' or not row['output']: abort(404)
            data=settings(root,row)
            data['backgrounds']=sorted(p.name for p in (assets/'backgrounds').glob('*') if p.suffix.lower() in ('.jpg','.mp4','.webm','.mov','.gif'))
            data['campaigns']=[c['name'] for c in read_json(campaigns,{'campaigns':[]})['campaigns'] if c.get('enabled',True)]
            return jsonify(data)
        finally: db.close()

    @app.post('/clips/<int:cid>/edit')
    def clip_edit(cid):
        from remontage import prepare
        from filelock import FileLock,Timeout
        from production_runs import set_status
        with lock:
            if (job['process'] and job['process'].poll() is None) or preview_lock.locked(): return jsonify(error='Сначала приостановите производство.'),409
            db=connect(dbpath)
            try:
                with FileLock(str(dbpath)+'.production.lock',timeout=0):
                    run_id=prepare(root,db,cid,request.form)
                try: launch_run(run_id)
                except OSError as exc:
                    set_status(db,run_id,'failed',str(exc))
                    with db: db.execute("UPDATE clips SET status='failed',error=? WHERE id=?",(str(exc),cid))
                    raise
                return jsonify(run_id=run_id)
            except (ValueError,KeyError,OSError,Timeout) as exc: return jsonify(error=str(exc)),400
            finally: db.close()

    @app.get('/api/clips/<int:cid>/versions')
    def clip_history(cid):
        from clip_versions import list_versions
        db=connect(dbpath)
        try: return jsonify(versions=list_versions(db,root,cid))
        finally: db.close()

    @app.post('/clips/<int:cid>/versions/<int:vid>/restore')
    def restore_clip_version(cid,vid):
        from clip_versions import restore
        from filelock import FileLock,Timeout
        with lock:
            if (job['process'] and job['process'].poll() is None) or preview_lock.locked(): return jsonify(error='Остановите производство'),409
            db=connect(dbpath)
            try:
                with FileLock(str(dbpath)+'.production.lock',timeout=0): restore(db,root,cid,vid)
            except (ValueError,OSError,Timeout) as exc: return jsonify(error=str(exc)),409
            finally: db.close()
        return jsonify(ok=True)

    @app.get('/clips/<int:cid>/versions/<int:vid>/video')
    def clip_history_media(cid,vid):
        from clip_versions import media
        db=connect(dbpath)
        try: path=media(db,root,cid,vid)
        finally: db.close()
        if path is None: abort(404)
        return send_file(path,mimetype='video/mp4',conditional=True)

    @app.get('/api/clips/<int:cid>')
    def clip_detail(cid):
        db=connect(dbpath)
        try:
            row=db.execute("SELECT c.*,v.title,v.url FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.id=?",(cid,)).fetchone()
            if not row or not row['output']: abort(404)
            p=(root/row['output']).resolve()
            if not p.is_relative_to(out.resolve()) or not p.is_file(): abort(404)
            return jsonify(id=cid,title=row['title'],status=row['status'],mode=row['mode'],duration=(row['actual_end'] or row['end'])-(row['actual_start'] if row['actual_start'] is not None else row['start']),campaign=row['campaign'],profile=row['production_profile'],run_id=row['run_id'],source='Локальный файл' if row['video_id'].startswith('local_') else 'Telegram' if row['video_id'].startswith('tg_') else 'YouTube',source_url=row['url'] if row['url'].startswith(('https://www.youtube.com/','https://t.me/')) else None,has_cover=bool(row['cover']),bytes=p.stat().st_size,quality=json.loads(row['quality_result'] or '{}'))
        finally: db.close()

    @app.post('/clips/bulk')
    def bulk_clips():
        import tempfile
        import zipfile
        from filelock import FileLock,Timeout
        try: ids=list(dict.fromkeys(int(x) for x in request.form.getlist('ids')))
        except ValueError: abort(400)
        if not 1<=len(ids)<=100 or min(ids)<1 or max(ids)>9223372036854775807: abort(400,'Select 1–100 clips')
        action=request.form.get('operation')
        if action not in ('archive','restore','remontage','export','purge'): abort(400)
        marks=','.join('?' for _ in ids)
        db=connect(dbpath)
        try:
            if action=='export':
                rows=db.execute(f"SELECT * FROM clips WHERE id IN ({marks}) AND output IS NOT NULL AND status!='archived'",ids).fetchall()
                if len(rows)!=len(ids): abort(400,'Export only completed clips')
                entries=[]
                for row in rows:
                    for key,ext in [('output','.mp4'),('cover','.jpg')]:
                        if not row[key]:
                            if key=='output': abort(409,'Output missing')
                            continue
                        p=(root/row[key]).resolve()
                        if not p.is_relative_to(out.resolve()) or p.suffix!=ext or not p.is_file(): abort(409,'Output missing')
                        entries.append((p,f"clip_{row['id']}{ext}"))
                if sum(p.stat().st_size for p,_ in entries)>512*1024**2: abort(400,'Export limit 512 MiB')
                fp=tempfile.TemporaryFile()
                try:
                    with zipfile.ZipFile(fp,'w',compression=zipfile.ZIP_STORED) as z:
                        for p,name in entries: z.write(p,name)
                    fp.seek(0)
                    response=send_file(fp,mimetype='application/zip',as_attachment=True,download_name='clipfactory-export.zip')
                    response.direct_passthrough=False
                    response.call_on_close(fp.close)
                    return response
                except BaseException:
                    fp.close()
                    raise
            try:
                with FileLock(str(dbpath)+'.production.lock',timeout=0):
                    if action=='purge':
                        from storage_control import purge
                        try: purge(db,root,ids)
                        except (ValueError,OSError) as exc: abort(409,str(exc))
                        return redirect(url_for('index',clip_status='archived')+'#clips')
                    with db:
                        db.execute('BEGIN IMMEDIATE')
                        rows=db.execute(f'SELECT id,status,output FROM clips WHERE id IN ({marks})',ids).fetchall()
                        if len(rows)!=len(ids): abort(404)
                        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publications'").fetchone():
                            if db.execute(f'SELECT 1 FROM publications WHERE clip_id IN ({marks}) LIMIT 1',ids).fetchone(): abort(409,'Selected clips have publication records')
                        allowed={'archive':('done','pending','failed','duplicate','ad_review','ad_rejected'),'restore':('archived',),'remontage':('done','failed','ad_review','ad_rejected')}[action]
                        if any(row['status'] not in allowed for row in rows): abort(409,'Invalid clip state for this action')
                        for row in rows:
                            if action=='archive':
                                db.execute("UPDATE clips SET archived_status=status,status='archived',archived_at=? WHERE id=?",(int(time.time()),row['id']))
                            elif action=='restore':
                                db.execute("UPDATE clips SET status=coalesce(archived_status,'pending'),archived_status=NULL,archived_at=NULL WHERE id=?",(row['id'],))
                            else:
                                db.execute("UPDATE clips SET status='pending',attempts=0,error=NULL,updated=? WHERE id=?",(int(time.time()),row['id']))
            except Timeout: abort(409,'Stop production before changing queue')
        finally: db.close()
        return redirect(url_for('index')+'#clips')

    @app.get('/clips/<int:cid>/cover')
    def cover(cid):
        db=connect(dbpath)
        try: row=db.execute("SELECT cover FROM clips WHERE id=?",(cid,)).fetchone()
        finally: db.close()
        if not row or not row['cover']: abort(404)
        path=(root/row['cover']).resolve()
        if not path.is_relative_to(out.resolve()) or not path.is_file() or path.suffix!='.jpg': abort(404)
        return send_file(path,mimetype='image/jpeg',conditional=True)

    @app.get('/clips/<int:cid>/video')
    def video(cid):
        db=connect(dbpath)
        try: row=db.execute("SELECT output FROM clips WHERE id=?",(cid,)).fetchone()
        finally: db.close()
        if not row or not row['output']: abort(404)
        path=(root/row['output']).resolve()
        if not path.is_relative_to(out.resolve()) or not path.is_file() or path.suffix!='.mp4': abort(404)
        return send_file(path,mimetype='video/mp4',conditional=True)
    app.extensions['factory_controller_loop']=controller_loop
    app.extensions['business_report_loop']=report_loop
    return app

if __name__=='__main__':
    data_root=Path(os.environ.get('CLIP_DATA_ROOT',str(ROOT))).resolve()
    data_root.mkdir(parents=True,exist_ok=True)
    app=create_app(data_root)
    threading.Thread(target=app.extensions['factory_controller_loop'],daemon=True,name='factory-controller').start()
    threading.Thread(target=app.extensions['business_report_loop'],daemon=True,name='business-reports').start()
    app.run(host=os.environ.get('CLIP_BIND_HOST','127.0.0.1'),port=8080,debug=False)
