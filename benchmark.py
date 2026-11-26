"""Benchmark the actual short renderer, without network or production data."""
import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

def run(root):
    import psutil
    from short_media import render_short
    from quality import verify
    from video_encoder import qsv_available
    root=Path(root).resolve()
    if shutil.disk_usage(root).free<512*1024**2: raise ValueError('Insufficient free space')
    result={'system':platform.platform(),'cpu':platform.processor(),'logical_cores':os.cpu_count(),
            'ram_gib':round(psutil.virtual_memory().total/1024**3,2),
            'qsv_available':qsv_available(),'results':[]}
    parent=psutil.Process()
    with tempfile.TemporaryDirectory(dir=root) as folder:
        folder=Path(folder)
        source=folder/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=30',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','5','-c:v','libx264',
            '-threads','2','-c:a','aac',str(source)],check=True,timeout=60)
        for mode in ['cpu']+(['qsv'] if result['qsv_available'] else []):
            peak=[0]
            stop=threading.Event()
            def sample():
                while not stop.is_set():
                    total=0
                    for proc in [parent,*parent.children(recursive=True)]:
                        try: total+=proc.memory_info().rss
                        except psutil.Error: pass
                    peak[0]=max(peak[0],total)
                    stop.wait(.15)
            thread=threading.Thread(target=sample,daemon=True)
            dest=folder/(mode+'.mp4')
            thread.start()
            start=time.perf_counter()
            try:
                actual=render_short(source,5,dest,template={'layout':'circle','size':640,'border':8},
                    background_path='',captions=False,normalize=True,encoder=mode)
                elapsed=time.perf_counter()-start
                quality=verify(dest,5,True)
                result['results'].append({'requested':mode,'actual':actual,'seconds':round(elapsed,2),
                    'fps_processing':round(150/elapsed,1),'peak_rss_mib':round(peak[0]/1024**2,1),
                    'bytes':quality['bytes'],'verified':True})
            except (ValueError,OSError,subprocess.SubprocessError) as exc:
                result['results'].append({'requested':mode,'verified':False,'error':str(exc)[:300]})
            finally:
                stop.set()
                thread.join()
    valid=[r for r in result['results'] if r.get('verified')]
    result['recommended']=min(valid,key=lambda r:r['seconds'])['actual'] if valid else None
    result['note']='Render-only synthetic test; excludes OCR, Whisper, downloads and visual quality comparison.'
    path=root/'benchmark-result.json'
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    args=p.parse_args()
    if not run(args.root)['recommended']: raise SystemExit(1)
