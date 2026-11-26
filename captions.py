"""Local word-timed captions; ASS rendering requires FFmpeg with libass."""
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def model():
    from faster_whisper import WhisperModel
    device=os.getenv('CLIP_DEVICE','cpu')
    return WhisperModel(os.getenv('CLIP_MODEL','small'),device=device,
                        compute_type=os.getenv('CLIP_COMPUTE','int8' if device=='cpu' else 'float16'))

def transcribe(source,start,end,wav):
    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-i',str(source),
                    '-t',str(end-start),'-vn','-ac','1','-ar','16000',str(wav)],check=True)
    segments,_=model().transcribe(str(wav),word_timestamps=True,vad_filter=True,
                                  language=os.getenv('CLIP_LANGUAGE') or None)
    return [(max(0,w.start),min(end-start,w.end),w.word.strip())
            for s in segments for w in (s.words or []) if w.word.strip() and w.start<end-start and w.end>w.start]

def stamp(t):
    n=max(0,round(t*100))
    return f'{n//360000}:{n//6000%60:02d}:{n//100%60:02d}.{n%100:02d}'

def clean(s):
    return s.replace('\\','／').replace('{','(').replace('}',')').replace('\n',' ')

def ass(words,font='DejaVu Sans',size=64,margin=480,highlight='00D5FF',style=None):
    from caption_style import validate,bgr
    s=validate(style) if style is not None else None
    if s:
        font,size,margin,highlight=s['font'],s['size'],s['margin'],bgr(s['highlight'])
    primary=bgr(s['color']) if s else 'FFFFFF'
    outline_color=bgr(s['outline_color']) if s else '000000'
    outline,shadow,alignment,word_limit=(s['outline'],s['shadow'],s['alignment'],s['words']) if s else (5,1,2,4)
    karaoke=s['karaoke'] if s else True
    if not re.fullmatch(r'[0-9A-Fa-f]{6}',highlight): raise ValueError('Expected BGR hex color')
    if not 20<=size<=120 or not 0<=margin<=1400: raise ValueError('Invalid caption layout')
    if any(c in font for c in ',\r\n'): raise ValueError('Invalid font')
    head=f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,{font},{size},&H00{primary},&H00{highlight},&H00{outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},{alignment},80,80,{margin},1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    groups=[]
    for a,b,w in sorted(words):
        if b<=a: continue
        if not groups or len(groups[-1])>=word_limit or a-groups[-1][-1][1]>.65 or sum(len(x[2])+1 for x in groups[-1])+len(w)>24:
            groups.append([])
        groups[-1].append((a,b,w))
    lines=[]
    for group in groups:
        if not karaoke:
            lines.append(f'Dialogue: 0,{stamp(group[0][0])},{stamp(group[-1][1])},Default,,0,0,0,,'+ ' '.join(clean(x[2]) for x in group))
            continue
        for i,(a,b,w) in enumerate(group):
            if i+1<len(group): b=max(a,min(group[i+1][0],max(b,group[i+1][0] if group[i+1][0]-b<=.25 else b)))
            if b<=a: continue
            text=' '.join(r'{\c&H'+highlight+r'&}'+clean(x[2])+r'{\c&H'+primary+r'&}' if j==i else clean(x[2]) for j,x in enumerate(group))
            lines.append(f'Dialogue: 0,{stamp(a)},{stamp(b)},Default,,0,0,0,,{text}')
    return head+'\n'.join(lines)+'\n'

def prepare(source,start,end,folder,style=None,words=None):
    import json
    if style is None and os.getenv('CLIP_CAPTION_STYLE'): style=json.loads(os.environ['CLIP_CAPTION_STYLE'])
    folder=Path(folder)
    from quality import inspect
    if words is None:
        words=transcribe(source,start,end,folder/'audio.wav') if any(s.get('codec_type')=='audio' for s in inspect(source).get('streams',[])) else []
    path=folder/'captions.ass'
    path.write_text(ass(words,font=os.getenv('CLIP_FONT','DejaVu Sans'),
                        size=int(os.getenv('CLIP_FONT_SIZE','64')),
                        margin=int(os.getenv('CLIP_CAPTION_MARGIN','480')),
                        highlight=os.getenv('CLIP_HIGHLIGHT','00D5FF'),style=style),encoding='utf-8')
    return path
