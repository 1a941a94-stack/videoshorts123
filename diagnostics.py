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
