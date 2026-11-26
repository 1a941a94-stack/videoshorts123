import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from short_media import candidate,render_short
from pipeline import connect,inspect_video,claim,approve_short,DEFAULTS

class ShortMediaTest(unittest.TestCase):
    def test_candidate(self):
        self.assertEqual(candidate({'duration':17,'view_count':100000})[0]['end'],17)
        self.assertFalse(candidate({'duration':61,'view_count':100000}))
        self.assertFalse(candidate({'duration':17,'view_count':100}))
        self.assertFalse(candidate({'duration':17,'view_count':100000,'is_live':True}))

    def test_queue(self):
        db=connect(':memory:')
        try:
            info=lambda url:{'duration':17,'view_count':100000,'title':'test'}
            for _ in range(2):
                self.assertEqual(inspect_video(db,{'id':'abcdefghijk'},DEFAULTS,info,'short'),'ready')
            self.assertEqual(db.execute('SELECT count(*) FROM clips').fetchone()[0],1)
            self.assertIsNone(claim(db,'long'))
            cid=db.execute('SELECT id FROM clips').fetchone()[0]
            self.assertEqual(claim(db,'short')['id'],cid)
            self.assertIsNone(claim(db,'short'))
        finally: db.close()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_render_templates(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x240:rate=10','-f','lavfi','-i','sine=frequency=440','-t','1','-c:v','libx264','-c:a','aac',str(source)],check=True)
            for layout in ('circle','rectangle'):
                dest=root/(layout+'.mp4')
                with patch.dict(os.environ,{'CLIP_SHORT_LAYOUT':layout,'CLIP_SHORT_BACKGROUND':'','CLIP_CAPTIONS':'0'}):
                    render_short(source,1,dest)
                r=subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(dest)],capture_output=True,text=True,check=True)
                streams=json.loads(r.stdout)['streams']
                video=next(s for s in streams if s['codec_type']=='video')
                self.assertEqual((video['width'],video['height']),(1080,1920))
                self.assertTrue(any(s['codec_type']=='audio' for s in streams))
