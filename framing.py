"""CPU face-aware framing. Uses bundled OpenCV cascade; no identity recognition."""
import math

def composition(width,height,faces):
    """Return crop dimensions and horizontal position, or None to preserve the scene."""
    cw=min(width,int(height*9/16)//2*2)
    ch=min(height,int(width*16/9)//2*2)
    if not faces or cw<2 or ch<2: return None
    left=min(x for x,y,w,h in faces)
    right=max(x+w for x,y,w,h in faces)
    if right-left>cw*.85: return None
    center=(left+right)/2
    x=max(0,min(width-cw,round(center-cw/2)))
    y=max(0,min(height-ch,round(min(y for x,y,w,h in faces)-ch*.2)))
    return cw,ch,x,y

def plan(source,start,end):
    import cv2
    cap=cv2.VideoCapture(str(source))
    try:
        if not cap.isOpened(): return None
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        detector=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
        if detector.empty(): return None
        samples=[]
        step=max(.5,(end-start)/60)
        t=start
        while t<end:
            cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
            ok,frame=cap.read()
            if ok:
                h,w=frame.shape[:2]
                ratio=min(1,640/w)
                small=cv2.resize(frame,(max(1,int(w*ratio)),max(1,int(h*ratio))))
                gray=cv2.equalizeHist(cv2.cvtColor(small,cv2.COLOR_BGR2GRAY))
                faces=[tuple(int(v/ratio) for v in box) for box in detector.detectMultiScale(gray,1.1,5,minSize=(24,24))]
                samples.append((t-start,composition(width,height,faces),bool(faces)))
            t+=step
        if not samples: return None
        found=[(t,c) for t,c,seen in samples if c]
        # Wide group shots retain the full image rather than cutting people out.
        if any(seen and c is None for _,c,seen in samples) or len(found)<len(samples)*.5: return None
        if not found: return None
        cw,ch=found[0][1][:2]
        # Interpolate sampled crop centers and smooth modest detection jitter.
        keys=[]
        for t,(_,_,x,y) in found:
            if keys and abs(x-keys[-1][1])<cw*.08: x=keys[-1][1]
            if keys and abs(y-keys[-1][2])<ch*.08: y=keys[-1][2]
            keys.append((t,x,y))
        def expr(axis):
            result=str(keys[-1][axis])
            for a,b in reversed(list(zip(keys,keys[1:]))):
                delta=b[0]-a[0]
                if delta>0:
                    segment=f'{a[axis]}+({b[axis]-a[axis]})*(t-{a[0]:.4f})/{delta:.4f}'
                    result=f'if(lt(t,{b[0]:.4f}),{segment},{result})'
            return f'if(lt(t,{keys[0][0]:.4f}),{keys[0][axis]},{result})'
        return f"crop={cw}:{ch}:x='{expr(1)}':y='{expr(2)}',scale=1080:1920,setsar=1"
    finally:
        cap.release()
