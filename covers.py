"""Generate a JPEG cover from the finished short, with optional branded text."""
import os
from pathlib import Path
import cv2
import numpy as np

def frame_score(frame):
    gray=cv2.cvtColor(cv2.resize(frame,(180,320)),cv2.COLOR_BGR2GRAY)
    mean=float(gray.mean())
    if mean<20 or mean>235: return -1
    return float(cv2.Laplacian(gray,cv2.CV_64F).var())**.5+float(gray.std())*.5

def generate(video,output,duration,mode='auto',title='',color='#172536',font_path=None):
    from PIL import Image,ImageDraw,ImageFont
    if mode not in ('auto','first','middle','branded'): raise ValueError('Invalid cover mode')
    cap=cv2.VideoCapture(str(video))
    best=None
    try:
        fractions=[.05] if mode=='first' else [.5] if mode=='middle' else [.1,.2,.35,.5,.65,.8,.9]
        for fraction in fractions:
            cap.set(cv2.CAP_PROP_POS_MSEC,max(0,duration*fraction*1000))
            ok,frame=cap.read()
            if not ok: continue
            score=frame_score(frame)
            if best is None or score>best[0]: best=(score,frame)
    finally: cap.release()
    if best is None: raise RuntimeError('Cannot decode cover frame')
    image=Image.fromarray(cv2.cvtColor(best[1],cv2.COLOR_BGR2RGB)).resize((1080,1920),Image.Resampling.LANCZOS)
    if mode=='branded':
        draw=ImageDraw.Draw(image)
        draw.rectangle((0,1580,1080,1920),fill=color)
        if title.strip():
            candidates=[font_path,os.getenv('CLIP_COVER_FONT'),str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'arial.ttf'),'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
            font=None
            for path in candidates:
                if path and Path(path).is_file():
                    font=ImageFont.truetype(path,64)
                    break
            if font is None: raise RuntimeError('Cover font unavailable')
            text=' '.join(title.split())[:80]
            for size in range(64,23,-4):
                font=ImageFont.truetype(font.path,size)
                if draw.textlength(text,font=font)<=980: break
            while text and draw.textlength(text,font=font)>980: text=text[:-1]
            draw.text((540,1750),text,font=font,fill='white',anchor='mm')
    output=Path(output)
    temp=output.with_suffix('.partial.jpg')
    try:
        image.save(temp,format='JPEG',quality=92,optimize=True)
        temp.replace(output)
    finally: temp.unlink(missing_ok=True)
    return output
