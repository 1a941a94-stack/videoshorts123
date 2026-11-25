"""Replay peak ranking and optional speech-boundary alignment."""
import math
from statistics import median

def select(info, length=45, count=3, threshold=.7):
    duration=float(info.get('duration') or 0)
    if length<=0 or count<=0 or duration<length: return []
    points=[]
    for p in info.get('heatmap') or []:
        try:
            a,b,v=map(float,(p['start_time'],p['end_time'],p['value']))
            if all(map(math.isfinite,(a,b,v))) and 0<=a<b<=duration+1 and 0<=v<=1:
                points.append((a,b,v))
        except (KeyError,TypeError,ValueError): continue
    points.sort()
    if not points: return []
    baseline=median(p[2] for p in points)
    candidates=[]
    i=0
    while i<len(points):
        j=i
        while j+1<len(points) and points[j+1][2]==points[i][2] and points[j+1][0]<=points[j][1]+.1: j+=1
        a,b,v=points[i][0],points[j][1],points[i][2]
        left=points[i-1][2] if i else baseline
        right=points[j+1][2] if j+1<len(points) else baseline
        if v>=threshold and v>=max(left,right) and (v>min(left,right) or len(points)==1):
            center=(a+b)/2
            start=max(0,min(duration-length,center-length*.4))
            nearby=[p[2] for p in points if p[0]<start+length and p[1]>start]
            prominence=max(0,v-baseline)
            rank=.65*v+.25*prominence+.10*(sum(nearby)/len(nearby) if nearby else v)
            candidates.append(dict(start=round(start,3),end=round(start+length,3),score=v,rank=round(rank,4),peak=round(center,3)))
        i=j+1
    chosen=[]
    for c in sorted(candidates,key=lambda p:(-p['rank'],-p['score'],p['start'])):
        if all(c['end']<=q['start'] or c['start']>=q['end'] for q in chosen): chosen.append(c)
        if len(chosen)>=count: break
    return chosen

def silence_boundaries(source, duration, noise='-35dB', minimum=.35):
    """Return midpoints of detected pauses; silence is not semantic understanding."""
    import subprocess,re
    result=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(source),'-vn','-af',f'silencedetect=noise={noise}:d={minimum}','-f','null','-'],capture_output=True,text=True,errors='replace',check=True)
    start=None
    cuts=[]
    for line in result.stderr.splitlines():
        m=re.search(r'silence_start:\s*([\d.]+)',line)
        if m: start=float(m.group(1))
        m=re.search(r'silence_end:\s*([\d.]+)',line)
        if m and start is not None:
            cuts.append((start+float(m.group(1)))/2); start=None
    return [0]+[x for x in cuts if 0<x<duration]+[duration]

def align(start,end,peak,boundaries,duration,tolerance=6,min_length=15,max_length=75):
    """Choose nearby pauses without dropping the replay peak."""
    starts=[start]+[x for x in boundaries if abs(x-start)<=tolerance]
    ends=[end]+[x for x in boundaries if abs(x-end)<=tolerance]
    options=[(a,b) for a in starts for b in ends if 0<=a<=peak<=b<=duration and min_length<=b-a<=max_length]
    if not options: return start,end
    pauses=set(boundaries)
    return min(options,key=lambda ab:(int(ab[0] not in pauses)+int(ab[1] not in pauses),abs(ab[0]-start)+abs(ab[1]-end)))
