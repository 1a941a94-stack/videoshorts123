"""Conservative duplicate detector for authorized short source media."""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np

VERSION=1
SAMPLES=12

def fingerprint(path,duration):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
    cap=cv2.VideoCapture(str(path))
    frames=[]
    try:
        for fraction in np.linspace(.08,.92,SAMPLES):
            cap.set(cv2.CAP_PROP_POS_MSEC,float(fraction*duration*1000))
            ok,frame=cap.read()
            if not ok: continue
            gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            # Low-detail frames are unreliable; never match only black screens.
            gray=cv2.resize(gray,(32,32),interpolation=cv2.INTER_AREA)
            if float(gray.std())<8: continue
            dct=cv2.dct(gray.astype(np.float32))[:8,:8].flatten()
            bits=dct>np.median(dct[1:])
            value=0
            for bit in bits: value=(value<<1)|int(bit)
            frames.append([round(float(fraction),3),f'{value:016x}'])
    finally: cap.release()
    return dict(version=VERSION,sha256=digest.hexdigest(),duration=float(duration),frames=frames)

def compare(a,b):
    if a['sha256']==b['sha256']: return 'exact',1.0
    if a['version']!=b['version']: return None
    if abs(a['duration']-b['duration'])>max(.6,min(a['duration'],b['duration'])*.04): return None
    left=dict(a['frames']); right=dict(b['frames'])
    pairs=[(int(left[t],16)^int(right[t],16)).bit_count() for t in left.keys() & right.keys()]
    if len(pairs)<9: return None
    # Require multiple distinct frames, not just a static common template.
    if len(set(left.values()))<5 or len(set(right.values()))<5: return None
    good=sum(d<=7 for d in pairs)
    if good>=9 and good/len(pairs)>=.9 and sum(pairs)/len(pairs)<=5:
        return 'visual',good/len(pairs)
    return None

def find_duplicate(db,cid,fp):
    rows=db.execute("""SELECT f.clip_id,f.payload FROM fingerprints f JOIN clips c ON c.id=f.clip_id
        WHERE f.clip_id<>? AND c.status='done' AND c.mode='short'
        AND (f.sha256=? OR abs(f.duration-?)<=?) ORDER BY f.clip_id""",
        (cid,fp['sha256'],fp['duration'],max(.6,fp['duration']*.05)))
    visual=None
    for row in rows:
        match=compare(fp,json.loads(row['payload']))
        if match:
            result=(row['clip_id'],*match)
            if match[0]=='exact': return result
            if visual is None or result[2]>visual[2]: visual=result
    return visual

def store(db,cid,fp):
    db.execute("""INSERT INTO fingerprints(clip_id,sha256,duration,payload) VALUES(?,?,?,?)
        ON CONFLICT(clip_id) DO UPDATE SET sha256=excluded.sha256,duration=excluded.duration,payload=excluded.payload""",
        (cid,fp['sha256'],fp['duration'],json.dumps(fp,separators=(',',':'))))
