"""Conservative local screening; no detection is a guarantee of ad-free media."""
import re
import hashlib
from functools import lru_cache
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

PROMO=re.compile(r'\b(?:промокод\w*|promo\s*code|bonus\s*code|регистрируй\w*|ставки\s+на\s+спорт|фрибет\w*|free\s*bet|бонус\s+за\s+регистрацию|ссылка\s+в\s+описании|реклама\s+от|sponsored\s+by|paid\s+promotion)\b',re.I)
DOMAIN=re.compile(r'(?:https?://|www\.)\S+|\b[a-z0-9][a-z0-9.-]+\.(?:ru|com|net|bet|gg|io|org|рф)\b',re.I)

def classify(text,brands=()):
    text=' '.join(text.lower().split())
    if PROMO.search(text): return 'promo_text'
    for brand in brands:
        if brand.strip() and re.search(r'(?<!\w)'+re.escape(brand.lower().strip())+r'(?!\w)',text):
            return 'known_advertiser'
    if DOMAIN.search(text): return 'domain'
    return None

@lru_cache(maxsize=4)
def languages(exe):
    result=subprocess.run([exe,'--list-langs'],capture_output=True,text=True,check=True,timeout=15)
    return frozenset(x.strip() for x in result.stdout.splitlines())

def screen(source,duration,brands=(),speech=True,reference_dir=None,transcript=None):
    import cv2
    from source_media import stage
    from diagnostics import tesseract_path
    exe=tesseract_path()
    if not exe:
        return 'review','Tesseract not installed; OCR unavailable'
    if not {'rus','eng'}.issubset(languages(exe)):
        return 'review','Tesseract rus and eng language packs required'
    from ad_visual import VisualAds
    visual=VisualAds(reference_dir) if reference_dir else None
    visual_hits={}
    cap=cv2.VideoCapture(str(source))
    qr=cv2.QRCodeDetector()
    findings=set()
    count=0
    ocr_cache={}
    ocr_env={**os.environ,'OMP_THREAD_LIMIT':'1'}
    try:
        with tempfile.TemporaryDirectory() as folder:
            framepath=Path(folder)/'frame.png'
            # Half-second sampling, including the opening and final frames.
            for i in range(max(1,int(duration*2)+1)):
                t=min(i*.5,max(0,duration-.15))
                cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
                ok,frame=cap.read()
                if not ok: continue
                count+=1
                h,w=frame.shape[:2]
                if max(h,w)>1280:
                    scale=1280/max(h,w)
                    frame=cv2.resize(frame,(round(w*scale),round(h*scale)))
                if visual:
                    match=visual.match(frame)
                    if match:
                        name,score,_=match
                        visual_hits[name]=visual_hits.get(name,0)+1
                        if visual_hits[name]>=2:
                            return 'rejected',f'Advertising reference {name} matched twice (score {score:.2f})'
                        findings.add(f'visual:{name}')
                detected,points=qr.detect(frame)
                if detected and points is not None:
                    try:
                        decoded,_=qr.decode(frame,points)
                    except (cv2.error,UnicodeError):
                        decoded=''
                    if decoded and decoded.strip(): findings.add('qr')
                key=(frame.shape,hashlib.sha256(frame.tobytes()).digest())
                if key not in ocr_cache:
                    if not cv2.imwrite(str(framepath),frame): raise RuntimeError('Cannot write OCR frame')
                    result=subprocess.run([exe,str(framepath),'stdout','-l','rus+eng','--psm','11'],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True,timeout=20,env=ocr_env)
                    ocr_cache[key]=classify(result.stdout,brands)
                hit=ocr_cache[key]
                if hit=='promo_text': return 'rejected',f'Advertising phrase at {t:.1f}s'
                if hit: findings.add(hit)
                if i%10==0: stage('ad_check',f'OCR {t:.1f}/{duration:.1f}s')
            if count<max(1,int(duration*2)*.8): return 'review','Insufficient decoded frames'
            if speech:
                from captions import transcribe
                probe=subprocess.run(['ffprobe','-v','error','-select_streams','a','-show_entries','stream=index','-of','csv=p=0',str(source)],capture_output=True,text=True,check=True,timeout=20)
                if probe.stdout.strip():
                    stage('ad_check','Speech advertising screening')
                    words=transcribe(source,0,duration,Path(folder)/'audio.wav')
                    if transcript is not None: transcript.extend(words)
                    hit=classify(' '.join(w for _,_,w in words),brands)
                    if hit=='promo_text': return 'rejected','Advertising phrase in speech'
                    if hit: findings.add(hit)
            else: return 'review','Speech screening disabled'
    finally: cap.release()
    return ('review',', '.join(sorted(findings))) if findings else ('clean','No advertising indicators detected in sampled frames or speech')
