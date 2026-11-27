import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class VisualRenderTest(unittest.TestCase):
    def test_motion_and_alpha(self):
        import cv2
        from short_media import render_short
        from banners import Banner
        from quality import verify
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def make(name,color,size,rate,duration):
                path=root/name
                subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                    f'color={color}:s={size}:r={rate}','-t',str(duration),'-c:v','libx264','-threads','2',str(path)],check=True)
                return path
            source=make('source.mp4','red','320x240',30,2)
            bg=make('bg.mp4','blue','180x320',15,.7)
            ad=make('ad.mp4','green','320x80',15,.7)
            out=root/'output.mp4'
            render_short(source,2,out,Banner(ad,position='top',start=.5,end=1.5),
                         template=dict(layout='circle',size=640,border=12,fit='cover',y=100),
                         background_path=str(bg),captions=False,normalize=True)
            result=verify(out,2,False)
            self.assertFalse(result['audio'])
            self.assertAlmostEqual(result['fps'],30)
            cap=cv2.VideoCapture(str(out))
            def frame(t):
                cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
                ok,img=cap.read()
                self.assertTrue(ok)
                return img
            try:
                a,b,c=(frame(t) for t in (.2,1,1.8))
                for img in (a,b,c):
                    # Campaign banners remain visible throughout the clip, even after looping.
                    self.assertGreater(int(img[250,540,1]),90)
                    self.assertLess(int(img[250,540,0]),40)
                    self.assertGreater(int(img[100,540,0]),200)
                    self.assertLess(int(img[100,540,1]),40)
                self.assertGreater(int(b[1060,540,2]),200)
                self.assertTrue(all(int(v)>220 for v in b[1060,210]))
                self.assertGreater(int(b[730,210,0]),200)
                self.assertLess(int(b[730,210,2]),40)
            finally: cap.release()
