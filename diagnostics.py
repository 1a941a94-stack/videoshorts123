import os
import shutil
import subprocess
import importlib.util
from pathlib import Path

def tesseract_path():
    explicit=os.getenv('CLIP_TESSERACT')
    if explicit: return explicit
    found=shutil.which('tesseract')
    if found: return found
    for key in ('ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA'):
        base=os.getenv(key)
        if base:
            for relative in ('Tesseract-OCR/tesseract.exe','Programs/Tesseract-OCR/tesseract.exe'):
                path=Path(base)/relative
                if path.is_file(): return str(path)
    return None

def readiness(root,mode='short'):
    result=[]
    def add(name,ok,detail,required=True):
        result.append(dict(name=name,ok=bool(ok),detail=detail,required=required))
    for command in ('ffmpeg','ffprobe'):
        path=shutil.which(command)
        add(command,path,path or 'Не найден в PATH')
    if mode=='short':
        exe=tesseract_path()
        langs=set()
        if exe:
            try:
                p=subprocess.run([exe,'--list-langs'],capture_output=True,text=True,timeout=10)
                if p.returncode==0: langs=set(p.stdout.splitlines())
            except (OSError,subprocess.SubprocessError): pass
        add('Tesseract OCR',exe,exe or 'Установите Tesseract OCR')
        add('Языки OCR',{'rus','eng'}.issubset(langs),'Доступны rus и eng' if {'rus','eng'}.issubset(langs) else 'Нужны языки rus и eng')
        add('Whisper',importlib.util.find_spec('faster_whisper') is not None,'Проверка установки; модель не загружается',False)
    free=shutil.disk_usage(root).free
    add('Свободное место',free>=3*1024**3,f'{free/1024**3:.1f} ГиБ свободно; минимум 3 ГиБ')
    return result


def factory_preflight(db, root, configs):
    """Local checks only; no external requests or credential disclosure."""
    from business_factory import load
    from business_resources import state as resources
    from account_lifecycle import init as lifecycle_init
    from account_sessions import describe
    cfg=load(db)
    item=configs.get(cfg['configuration'])
    checks=[]
    def add(name, ok, detail, required=True):
        checks.append(dict(name=name,ok=bool(ok),detail=detail,required=required))
    add('Конфигурация монтажа',item,'Сохранена' if item else 'Выберите конфигурацию')
    if item:
        checks.extend(readiness(root,item['mode']))
    res=resources(db)
    add('Бюджет',not any(res['over']),'Лимит достигнут' if any(res['over']) else 'Лимиты не превышены')
    add('Срок услуг',not res['expired'],f"Истекло услуг: {res['expired']}",False)
    lifecycle_init(db)
    accounts=[dict(r) for r in db.execute("""SELECT a.*, l.state AS lifecycle,
        EXISTS(SELECT 1 FROM publications p WHERE p.account_id=a.id AND p.status IN ('blocked','browser_blocked','uncertain')) AS issues
        FROM accounts a LEFT JOIN account_lifecycle l ON l.account_id=a.id
        WHERE a.enabled=1 AND a.platform IN ('telegram','instagram','youtube')
        AND (l.state IS NULL OR l.state NOT IN ('archived','paused','review'))
        AND (l.state IS NULL OR l.state!='scheduled' OR l.start_at<=CAST(strftime('%s','now') AS INTEGER))""")]
    connected=sum(describe(root,a)=='Локальные данные есть; вход не проверен' for a in accounts)
    add('Подключения API',connected>0,f'Локальные данные: {connected} из {len(accounts)}; удалённый вход не проверен',False)
    if item:
        pending=db.execute("SELECT count(*) FROM clips WHERE status='pending' AND mode=?",(item['mode'],)).fetchone()[0]
        add('Исходники выбранного режима',pending>0,f'В очереди: {pending}; автоимпорт коротких видео из incoming-media при включённом автопоиске',False)
    return checks
