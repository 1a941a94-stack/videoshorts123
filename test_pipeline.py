import tempfile
import unittest
from pathlib import Path
from pipeline import connect, add_source, scan, claim, DEFAULTS

class PipelineTest(unittest.TestCase):
    def test_discovery_and_deduplication(self):
        with tempfile.TemporaryDirectory() as folder:
            db=connect(Path(folder)/'test.sqlite3')
            try:
                add_source(db,'test')
                add_source(db,'test')
                settings=dict(DEFAULTS,delay=0,min_views=1)
                finder=lambda q,n:[{'id':'abcdefghijk'},{'id':'abcdefghijk'}]
                extractor=lambda url:{'title':'test','view_count':500,'duration':180,'heatmap':[{'start_time':30,'end_time':40,'value':.95}]}
                self.assertEqual(scan(db,settings,finder,extractor),{'ready':1,'cached':1})
                self.assertEqual(db.execute('SELECT count(*) FROM clips').fetchone()[0],1)
                self.assertIsNotNone(claim(db))
                self.assertIsNone(claim(db))
            finally: db.close()

    def test_filter(self):
        db=connect(':memory:')
        try:
            add_source(db,'test')
            self.assertEqual(scan(db,dict(DEFAULTS,delay=0),lambda q,n:[{'id':'abcdefghijk'}],lambda url:{'duration':180,'view_count':2}),{'filtered':1})
            self.assertIsNone(claim(db))
        finally: db.close()
