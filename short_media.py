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

def render_short(source,duration,output,banner=None,*,template=None,background_path=None,captions=None,normalize=None,caption_style=None,words=None,encoder=None):
    source=Path(source).resolve()
    output=Path(output).resolve()
    import json
    from short_templates import validate
    spec=validate(template if template is not None else json.loads(os.getenv('CLIP_SHORT_TEMPLATE','{}')) or {'layout':os.getenv('CLIP_SHORT_LAYOUT','circle'),'size':960 if os.getenv('CLIP_SHORT_LAYOUT','circle')=='circle' else 1000})
    spec_style=spec.get('caption_style')
    layout=spec['layout']
    size=spec['size']; border=spec['border']; half=size/2
    fit=spec['fit']; color=spec['color'].replace('#','0x'); border_color=spec['border_color'].replace('#','0x')
    if layout not in ('circle','rectangle'): raise ValueError('Invalid short layout')
    background=os.getenv('CLIP_SHORT_BACKGROUND','') if background_path is None else background_path
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source)]
    prefix='[0:v]'
    if fit=='cover' and spec['auto_crop']:
        from auto_crop import detect
        crop=detect(source,duration)
        if crop:
            prefix+='crop='+':'.join(map(str,crop))+','
            stage('framing','Stable black margins removed')
    # The source is contained or cropped into a square; the mask is applied last.
    if fit=='cover':
        vf=f"{prefix}scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size},setsar=1"
    else:
        vf=f"[0:v]scale={size}:{size}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    zoom=spec['source_zoom']
    if zoom>100:
        scaled=2*math.ceil(size*zoom/200)
        px=(spec['source_pan_x']+100)/200
        py=(spec['source_pan_y']+100)/200
        vf+=f",scale={scaled}:{scaled},crop={size}:{size}:trunc((iw-ow)*{px}/2)*2:trunc((ih-oh)*{py}/2)*2"
    outer=size+2*border
    if layout=='rectangle' and border:
        vf+=f",pad={outer}:{outer}:{border}:{border}:color={border_color}"
    vf+=',fps=30[foreground]'
    if layout=='rectangle': vf+=';[foreground]null[fg]'
    # Background is optional; otherwise use a dark blue canvas.
    if background:
        from banners import MOTION_EXT,media_input
        cmd+=media_input(background) if Path(background).suffix.lower() in MOTION_EXT else ['-loop','1','-framerate','30','-i',str(Path(background).resolve())]
        vf+=";[1:v]setpts=PTS-STARTPTS,fps=30,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg]"
        ad_index=2
    else:
        vf+=f";color=c={color}:s=1080x1920:r=30[bg]"
        ad_index=1
    if layout=='circle':
        mask_index=ad_index
        ad_index+=1
        cmd+=['-i','circle-mask.png']
        vf+=f";[foreground]format=rgba[inner];[{mask_index}:v]format=gray[alpha];[inner][alpha]alphamerge[masked]"
        if border:
            ring_index=ad_index
            ad_index+=1
            cmd+=['-loop','1','-framerate','30','-i','circle-ring.png']
            vf+=f";[{ring_index}:v]format=rgba[ring];[ring][masked]overlay={border}:{border}:format=rgb:shortest=1[fg]"
        else: vf+=';[masked]null[fg]'
    vf+=f";[bg][fg]overlay=(W-w)/2+({spec['x']}):(H-h)/2+({spec['y']}):shortest=1"
    if banner:
        from banners import Banner,media_input
        ad_layout=spec.get('ad_layout')
        spec=banner if isinstance(banner,Banner) else Banner(Path(banner))
        if ad_layout:
            from dataclasses import replace
            spec=replace(spec,position='center',margin=0,**ad_layout)
        cmd+=media_input(spec.path)
        vf+=spec.filter(duration).replace('[1:v]',f'[{ad_index}:v]')
    else: vf+='[v]'
    with tempfile.TemporaryDirectory() as folder:
        if layout=='circle':
            from PIL import Image,ImageDraw
            def disk(n,fill,mode,path):
                image=Image.new(mode,(n*3,n*3),0 if mode=='L' else (0,0,0,0))
                ImageDraw.Draw(image).ellipse((0,0,n*3-1,n*3-1),fill=fill)
                image.resize((n,n),Image.Resampling.LANCZOS).save(Path(folder)/path)
            disk(size,255,'L','circle-mask.png')
            if border: disk(outer,tuple(bytes.fromhex(border_color[2:]))+(255,),'RGBA','circle-ring.png')
        if captions if captions is not None else os.getenv('CLIP_CAPTIONS','0')=='1':
            from captions import prepare
            stage('captions')
            if caption_style is None:
                caption_style=spec_style
            prepare(source,0,duration,folder,style=caption_style,words=words)
            vf=vf.removesuffix('[v]')+'[pre];[pre]ass=captions.ass[v]'
        stage('render',layout)
        audio=['-af','loudnorm=I=-16:TP=-1.5:LRA=11','-ar','48000','-b:a','160k'] if (normalize if normalize is not None else os.getenv('CLIP_NORMALIZE_AUDIO','1')=='1') else []
        cmd+=['-filter_complex_threads','1','-filter_complex',vf,'-map','[v]','-map','0:a?',
              '-t',str(duration)]
        from video_encoder import encode
        return encode(cmd,['-c:a','aac',*audio,'-movflags','+faststart'],output,folder,mode=encoder,report=lambda msg:stage('render',msg))
