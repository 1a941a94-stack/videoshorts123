"""Local visual screening using tightly cropped advertising reference images."""
import cv2
import numpy as np
from pathlib import Path

SCALES=(.25,.35,.5,.7,1.,1.4,2.)
THRESHOLD=.88

class VisualAds:
    def __init__(self,folder):
        self.references=[]
        for path in sorted(Path(folder).glob('*.png')):
            image=cv2.imdecode(np.fromfile(str(path),dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
            if image is None: raise ValueError(f'Invalid reference: {path.name}')
            if min(image.shape)<20 or image.std()<8: raise ValueError(f'Low-detail reference: {path.name}')
            templates=[]
            for scale in SCALES:
                w,h=round(image.shape[1]*scale),round(image.shape[0]*scale)
                if min(w,h)<20: continue
                resized=cv2.resize(image,(w,h),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
                templates.append(resized)
            self.references.append((path.stem,templates))

    def match(self,frame):
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        best=None
        for name,templates in self.references:
            for template in templates:
                h,w=template.shape
                if h>gray.shape[0] or w>gray.shape[1]: continue
                scores=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED)
                _,score,_,pos=cv2.minMaxLoc(scores)
                if score>=THRESHOLD and (best is None or score>best[1]):
                    best=(name,float(score),pos)
        return best
