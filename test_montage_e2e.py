import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class MontageIntegrationTest(unittest.TestCase):
    def test_local_import_and_render(self):
        from pipeline import connect,process
        from local_import import import_file
        from quality import verify
        from PIL import Image
        from banners import Banner
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            src=root/'original.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x240:rate=30','-f','lavfi','-i','sine=frequency=440','-t','6','-c:v','libx264','-threads','2','-c:a','aac',str(src)],check=True)
            db=connect(root/'clipfactory.sqlite3')
            self.addCleanup(db.close)
            self.assertEqual(import_file(db,root,src),'ready')
            self.assertEqual(import_file(db,root,src),'duplicate')
            banner=root/'banner.png'
            Image.new('RGBA',(800,180),(255,0,0,220)).save(banner)
            spec=dict(layout='circle',size=640,border=12,fit='cover',y=100)
            env={'CLIP_SHORT_TEMPLATE':json.dumps(spec),'CLIP_SHORT_BACKGROUND':'','CLIP_CAPTIONS':'0','CLIP_COVER_MODE':'auto','CLIP_PRODUCTION_PROFILE':'test','CLIP_NORMALIZE_AUDIO':'1'}
            # Synthetic fixture has no advertising. This test exercises downstream
            # integration, not OCR/Whisper accuracy.
            with patch.dict(os.environ,env),patch('ad_filter.screen',return_value=('clean','synthetic fixture')):
                self.assertTrue(process(db,root/'output',banner=Banner(banner,position='top'),mode='short'))
            row=db.execute('SELECT * FROM clips').fetchone()
            self.assertEqual(row['status'],'done',row['error'])
            self.assertEqual(row['production_profile'],'test')
            self.assertTrue(Path(row['cover']).is_file(),row['cover_error'])
            self.assertTrue(json.loads(row['quality_result'])['audio'])
            verify(row['output'],6,True)
            self.assertFalse(process(db,root/'output',mode='short'))
            db.close()
