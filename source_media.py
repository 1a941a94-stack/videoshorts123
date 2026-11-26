"""Cache authorized source media; refine clip boundaries using local audio."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import os
import time
from pathlib import Path
from filelock import FileLock

def stage(name,detail=''):
    print('CF_STAGE '+json.dumps({'stage':name,'detail':detail},ensure_ascii=True),flush=True)

def probe(path):
    r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],capture_output=True,text=True,check=True,timeout=30)
    return float(json.loads(r.stdout)['format']['duration'])

def cached_source(url,vid,root):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',vid): raise ValueError('Invalid video ID')
    root=Path(root).resolve()
    root.mkdir(parents=True,exist_ok=True)
    dest=root/(vid+'.mp4')
    # Serialize downloads and eviction; callers hold a per-source lock during use.
    if dest.is_file():
        try:
            if probe(dest)>0:
                os.utime(dest,None)
                stage('cache','Existing local source')
                return dest
        except (ValueError,KeyError,subprocess.SubprocessError): pass
        dest.unlink(missing_ok=True)
    if shutil.disk_usage(root).free<3*1024**3: raise RuntimeError('Not enough free disk space for download')
    stage('download','Native downloader, full source')
    with tempfile.TemporaryDirectory(prefix='source-',dir=root) as folder:
        full=Path(folder)/'full.mp4'
        subprocess.run([sys.executable,'-m','yt_dlp','--no-playlist','--newline','--downloader','native',
            '--socket-timeout','25','--retries','2','--fragment-retries','2','--max-filesize','1G',
            '-f','bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]',
            '--merge-output-format','mp4','--remux-video','mp4','-o',str(full),url],check=True,timeout=900)
        if not full.is_file() or probe(full)<=0: raise RuntimeError('No valid downloaded source')
        full.replace(dest)
    return dest

def pauses(source,lo,hi):
    cmd=['ffmpeg','-hide_banner','-nostats','-ss',str(lo),'-i',str(source),'-t',str(hi-lo),
        '-vn','-af','silencedetect=noise=-35dB:d=0.35','-f','null','-']
    r=subprocess.run(cmd,capture_output=True,text=True,errors='replace',check=True,timeout=120)
    points=[]
    start=None
    for line in r.stderr.splitlines():
        a=re.search(r'silence_start:\s*(-?[\d.]+)',line)
        if a: start=float(a[1])
        b=re.search(r'silence_end:\s*(-?[\d.]+)',line)
        if b and start is not None:
            t=lo+(start+float(b[1]))/2
            if lo<t<hi: points.append(t)
            start=None
    return points

def boundaries(start,end,peak,duration,points,sentences=()):
    """Prefer sentence boundaries, then silence. Preserve peak; avoid unbounded extension."""
    if not 0<=start<end<=duration or not start<=peak<=end: raise ValueError('Invalid clip interval')
    target=end-start
    minimum=min(20,target)
    maximum=max(75,target)
    starts=[(start,0)]+[(p,1) for p in points if start-8<=p<=start+5]+[(p,2) for p in sentences if start-8<=p<=start+5]
    ends=[(end,0)]+[(p,1) for p in points if end-4<=p<=end+15]+[(p,2) for p in sentences if end-4<=p<=end+15]
    candidates=[(a,b,qa,qb) for a,qa in starts for b,qb in ends if 0<=a<=peak<=b<=duration and minimum<=b-a<=maximum]
    if not candidates: return start,end,'unadjusted'
    a,b,qa,qb=min(candidates,key=lambda c:(-c[3],-c[2],abs(c[0]-start)+abs(c[1]-end)))
    return round(a,3),round(b,3),'sentence' if qa==2 or qb==2 else 'pause' if qa or qb else 'unadjusted'

def refine(source,start,end,peak):
    duration=probe(source)
    if end>duration+0.5: raise ValueError('Source shorter than planned clip')
    end=min(end,duration)
    peak=max(start,min(peak,end))
    lo=max(0,start-12); hi=min(duration,end+18)
    stage('boundaries','Analyzing speech boundaries')
    try: points=pauses(source,lo,hi)
    except subprocess.SubprocessError: points=[]
    sentences=[]
    if os.getenv('CLIP_SMART_SPEECH','0')=='1':
        stage('speech','Local Whisper boundary analysis')
        from captions import transcribe
        with tempfile.TemporaryDirectory() as folder:
            words=transcribe(source,lo,hi,Path(folder)/'audio.wav')
        for i,(a,b,w) in enumerate(words):
            if w.rstrip('»”"').endswith(('.','!','?','…')):
                sentences.append(min(hi,lo+b+.12))
                if i+1<len(words): sentences.append(max(lo,lo+words[i+1][0]-.12))
    a,b,method=boundaries(start,end,peak,duration,points,sentences)
    stage('boundaries',f'{a:.1f}–{b:.1f} s / {method}')
    return a,b,method
