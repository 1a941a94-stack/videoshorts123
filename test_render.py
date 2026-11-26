import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from clipfactory import render

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class RenderTest(unittest.TestCase):
    def test_vertical_banner(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'source.mp4'
            banner=root/'banner.png'
            output=root/'result.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=320x180:r=10','-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True)
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=red:s=200x50','-frames:v','1','-threads','1',str(banner)],check=True)
            with patch.dict('os.environ',{'CLIP_CAPTIONS':'0'}):
                render(source,0,1,output,banner)
            data=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(output)]))
            self.assertEqual((data['streams'][0]['width'],data['streams'][0]['height']),(1080,1920))
