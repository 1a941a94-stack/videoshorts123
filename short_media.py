"""Short-video candidates and local compositing. Only use media authorized for reuse."""
import math
import os
import subprocess
import tempfile
from pathlib import Path
from source_media import stage

def candidate(info,min_views=10000):
    duration=float(info.get('duration') or 0)
    views=int(info.get('view_count') or 0)
    if info.get('is_live') or info.get('live_status') in ('is_live','is_upcoming') or not 5<=duration<=60 or views<min_views:
        return []
    # Popularity proxy, not a replay score or prediction of virality.
    score=min(1,math.log10(max(1,views))/7)
    return [dict(start=0,end=duration,score=score,rank=score,peak=None)]

def render_short(source,duration,output,banner=None):
    source=Path(source).resolve()
    output=Path(output).resolve()
    layout=os.getenv('CLIP_SHORT_LAYOUT','circle')
    if layout not in ('circle','rectangle'): raise ValueError('Invalid short layout')
    background=os.getenv('CLIP_SHORT_BACKGROUND','')
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source)]
    # Circular mask clips corners; rectangular layout preserves the entire image.
    if layout=='circle':
        vf="[0:v]scale=960:960:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=960:960:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(sqrt((X-480)*(X-480)+(Y-480)*(Y-480)),478),255,0)'[fg]"
    else:
        vf="[0:v]scale=1000:1000:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[fg]"
    # Background is optional; otherwise use a dark blue canvas.
    if background:
        cmd+=['-loop','1','-framerate','30','-i',str(Path(background).resolve())]
        vf+=";[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg]"
        ad_index=2
    else:
        vf+=";color=c=0x172536:s=1080x1920:r=30[bg]"
        ad_index=1
    vf+=";[bg][fg]overlay=(W-w)/2:(H-h)/2+80:shortest=1"
    if banner:
        from banners import Banner
        from dataclasses import replace
        spec=banner if isinstance(banner,Banner) else Banner(Path(banner))
        spec=replace(spec,position='top',margin=160,height=min(spec.height,280))
        cmd+=['-i',str(spec.path.resolve())]
        vf+=spec.filter(duration).replace('[1:v]',f'[{ad_index}:v]')
    else: vf+='[v]'
    with tempfile.TemporaryDirectory() as folder:
        if os.getenv('CLIP_CAPTIONS','0')=='1':
            from captions import prepare
            stage('captions')
            prepare(source,0,duration,folder)
            vf=vf.removesuffix('[v]')+'[pre];[pre]ass=captions.ass[v]'
        stage('render',layout)
        cmd+=['-filter_complex_threads','1','-filter_complex',vf,'-map','[v]','-map','0:a?',
              '-t',str(duration),'-c:v','libx264','-threads','2','-preset','veryfast','-crf','22',
              '-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(output)]
        subprocess.run(cmd,check=True,cwd=folder,timeout=600)
