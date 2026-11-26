"""Local technical quality gate; no remote calls."""
import json
import math
import subprocess
from pathlib import Path
from fractions import Fraction

def inspect(path):
    result=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,check=True,timeout=30)
    return json.loads(result.stdout)

def verify(path,expected_duration,require_audio=False):
    path=Path(path)
    if not path.is_file() or path.stat().st_size<1024: raise ValueError('Empty or truncated output')
    data=inspect(path)
    streams=data.get('streams',[])
    video=[s for s in streams if s.get('codec_type')=='video']
    audio=[s for s in streams if s.get('codec_type')=='audio']
    if len(video)!=1 or len(audio)>1: raise ValueError('Unexpected output streams')
    v=video[0]
    if (v.get('width'),v.get('height'))!=(1080,1920) or v.get('codec_name')!='h264' or v.get('pix_fmt')!='yuv420p': raise ValueError('Output is not compatible vertical H264')
    duration=float(data['format']['duration'])
    if not math.isfinite(duration) or abs(duration-expected_duration)>max(.5,expected_duration*.025): raise ValueError('Rendered duration differs from source')
    if require_audio and not audio: raise ValueError('Original audio missing')
    if audio and audio[0].get('codec_name')!='aac': raise ValueError('Expected AAC audio')
    fps=float(Fraction(v.get('avg_frame_rate','0/1')))
    if not 1<=fps<=60: raise ValueError('Invalid frame rate')
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-map','0:v:0','-map','0:a?','-f','null','-'],capture_output=True,check=True,timeout=300)
    return dict(width=1080,height=1920,duration=duration,fps=fps,audio=bool(audio),bytes=path.stat().st_size)
