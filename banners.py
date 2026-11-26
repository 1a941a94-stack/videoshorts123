"""Validated local banner campaigns and FFmpeg overlay configuration."""
from dataclasses import dataclass
from pathlib import Path
import json
import math
import random
from datetime import datetime, timezone

MOTION_EXT={'.mp4','.webm','.mov','.gif'}
IMAGE_EXT={'.png','.jpg','.jpeg','.webp'}

def media_input(path):
    path=Path(path).resolve()
    return (['-stream_loop','-1','-i',str(path)] if path.suffix.lower() in MOTION_EXT else ['-i',str(path)])

@dataclass(frozen=True)
class Banner:
    path: Path
    name: str = 'manual'
    width: int = 1000
    height: int = 260
    position: str = 'bottom'
    margin: int = 180
    opacity: float = 1.0
    start: float = 0.0
    end: float | None = None

    def __post_init__(self):
        if not self.path.is_file(): raise ValueError(f'Banner not found: {self.path}')
        if self.path.suffix.lower() not in IMAGE_EXT | MOTION_EXT: raise ValueError('Unsupported banner media')
        if not 1<=self.width<=1080 or not 1<=self.height<=1920: raise ValueError('Invalid dimensions')
        if self.position not in ('top','bottom','center'): raise ValueError('Invalid position')
        if not 0<=self.margin<=1920-self.height: raise ValueError('Invalid margin')
        if not math.isfinite(self.opacity) or not 0<=self.opacity<=1: raise ValueError('Invalid opacity')
        if not math.isfinite(self.start) or self.start<0: raise ValueError('Invalid start')
        if self.end is not None and (not math.isfinite(self.end) or self.end<=self.start): raise ValueError('Invalid end')

    def filter(self, duration):
        end=min(duration,self.end if self.end is not None else duration)
        if end<=self.start: raise ValueError('Banner interval does not intersect clip')
        y={'top':str(self.margin),'bottom':f'H-h-{self.margin}','center':'(H-h)/2'}[self.position]
        return (f'[base];[1:v]setpts=PTS-STARTPTS,scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,'
                f'format=rgba,colorchannelmixer=aa={self.opacity}[ad];'
                f"[base][ad]overlay=(W-w)/2:{y}:enable='gte(t,{self.start})*lt(t,{end})'[v]")

def choose(config, duration, rng=None):
    config=Path(config).resolve()
    data=json.loads(config.read_text(encoding='utf-8'))
    active=[]
    weights=[]
    now=datetime.now(timezone.utc)
    for row in data['campaigns']:
        if not row.get('enabled',True): continue
        for field in ('active_from','active_until'):
            if row.get(field):
                dt=datetime.fromisoformat(row[field].replace('Z','+00:00'))
                if dt.tzinfo is None: raise ValueError('Campaign timestamps require timezone')
                if (field=='active_from' and now<dt) or (field=='active_until' and now>=dt): break
        else:
            weight=float(row.get('weight',1))
            if not math.isfinite(weight) or weight<=0: raise ValueError('Invalid campaign weight')
            spec={k:row[k] for k in ('name','width','height','position','margin','opacity','start','end') if k in row}
            banner=Banner(path=(config.parent/row['path']).resolve(),**spec)
            if banner.start<duration:
                active.append(banner)
                weights.append(weight)
    if not active: raise ValueError('No eligible active banner campaign')
    return (rng or random).choices(active,weights=weights,k=1)[0]
