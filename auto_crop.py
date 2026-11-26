"""Conservative black-border detection; never crop based on a single dark frame."""
import re
import subprocess
from collections import Counter

def detect(source,duration):
    crops=[]
    for fraction in (.15,.45,.75):
        try:
            p=subprocess.run(['ffmpeg','-hide_banner','-ss',str(max(0,duration*fraction)),'-i',str(source),'-t','0.7','-an','-vf','cropdetect=limit=18:round=2:reset=0','-f','null','-'],capture_output=True,text=True,timeout=15)
            matches=re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)',p.stderr)
            if p.returncode or not matches: return None
            crops.append(tuple(map(int,matches[-1])))
        except (OSError,subprocess.SubprocessError): return None
    (w,h,x,y),count=Counter(crops).most_common(1)[0]
    if count!=len(crops) or min(w,h)<160 or min(x,y)<0 or max(x,y)<8: return None
    # Avoid cutting away most of a dark scene or an intentionally off-centre subject.
    if x>w or y>h: return None
    return w,h,x,y
