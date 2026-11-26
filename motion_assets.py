import json
import math
import subprocess
from pathlib import Path

def validate_motion(path):
    path=Path(path)
    if not 0<path.stat().st_size<=64*1024**2: raise ValueError('Motion file exceeds 64 MiB')
    result=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height:format=duration','-of','json',str(path)],capture_output=True,text=True,timeout=20,check=True)
    data=json.loads(result.stdout)
    streams=data.get('streams',[])
    if not streams: raise ValueError('No video stream')
    w,h=int(streams[0]['width']),int(streams[0]['height'])
    duration=float(data['format']['duration'])
    if not 16<=min(w,h)<=max(w,h)<=4096 or not math.isfinite(duration) or not .05<=duration<=120:
        raise ValueError('Motion asset must be 0.05–120 seconds and no larger than 4096 pixels')
    subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-frames:v','1','-f','null','-'],check=True,timeout=30,capture_output=True)
