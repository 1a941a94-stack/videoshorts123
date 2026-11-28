import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from incoming_media import ingest

class IncomingMediaTest(unittest.TestCase):
    def test_stable_files_and_deduplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/'incoming-media'
            folder.mkdir()
            for name in ('a.mp4','b.mp4','new.mp4'):
                p=folder/name
                p.write_bytes(b'video')
                os.utime(p,(100,100 if name!='new.mp4' else 195))
            db=sqlite3.connect(':memory:')
            self.addCleanup(db.close)
            calls=[]
            def importer(db,root,path):
                calls.append(path.name)
                return 'ready'
            self.assertEqual(ingest(db,root,1,200,importer)['added'],1)
            self.assertEqual(ingest(db,root,5,200,importer)['added'],1)
            self.assertEqual(calls,['a.mp4','b.mp4'])
            self.assertEqual(ingest(db,root,5,240,importer)['added'],1)
            self.assertEqual(ingest(db,root,5,240,importer)['added'],0)
