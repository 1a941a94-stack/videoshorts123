import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pipeline import connect,claim
from production_runs import create,summary
from batch_worker import run
from short_templates import validate
from clip_versions import remember,restore
from storage_control import purge

class ProductionRegression(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.out=self.root/'output'
        self.out.mkdir()
        self.db=connect(self.root/'clipfactory.sqlite3')
        self.addCleanup(self.db.close)
        with self.db:
            self.db.execute("INSERT INTO videos(id,url,status,checked) VALUES('example','https://example.invalid','ready',0)")
    def add_clip(self,start=0):
        with self.db:
            return self.db.execute("INSERT INTO clips(video_id,start,end,score,mode,updated) VALUES('example',?,?,1,'short',0)",(start,start+6)).lastrowid
    def batch(self,search=False):
        return create(self.db,1,dict(mode='short',env={},campaigns=None,auto_search=search))
    def test_ownership(self):
        cid=self.add_clip()
        rid=self.batch()
        self.assertEqual(claim(self.db,'short',rid)['id'],cid)
        with self.db:self.db.execute("UPDATE clips SET status='pending' WHERE id=?",(cid,))
        self.assertIsNone(claim(self.db,'short'))
        self.assertIsNone(claim(self.db,'short',self.batch()))
        self.assertEqual(claim(self.db,'short',rid)['id'],cid)
    def test_empty_batch_bounded(self):
        rid=self.batch(True)
        with patch('batch_worker.shutil.disk_usage') as disk,patch('pipeline.scan') as scan:
            disk.return_value.free=10*1024**3
            run(self.db,self.root,self.out,rid,{})
        self.assertEqual(scan.call_count,3)
        self.assertEqual(summary(self.db,rid)['status'],'exhausted')
    def test_success_counts_toward_goal(self):
        cid=self.add_clip()
        rid=self.batch()
        def process(db,*args,**kw):
            with db:db.execute("UPDATE clips SET status='done' WHERE id=?",(cid,))
        with patch('batch_worker.shutil.disk_usage') as disk,patch('pipeline.process',side_effect=process):
            disk.return_value.free=10*1024**3
            run(self.db,self.root,self.out,rid,{})
        self.assertEqual(summary(self.db,rid)['counts'],{'done':1})
        self.assertEqual(summary(self.db,rid)['status'],'completed')
    def test_version_restore_and_purge(self):
        cid=self.add_clip()
        old=self.out/'old.mp4';new=self.out/'new.mp4'
        old.write_bytes(b'old');new.write_bytes(b'new')
        with self.db:
            self.db.execute("UPDATE clips SET status='done',output=? WHERE id=?",(str(old),cid))
            remember(self.db,self.db.execute('SELECT * FROM clips WHERE id=?',(cid,)).fetchone())
            self.db.execute('UPDATE clips SET output=? WHERE id=?',(str(new),cid))
        vid=self.db.execute('SELECT id FROM clip_versions WHERE clip_id=?',(cid,)).fetchone()[0]
        restore(self.db,self.root,cid,vid)
        self.assertEqual(self.db.execute('SELECT output FROM clips WHERE id=?',(cid,)).fetchone()[0],str(old))
        self.assertTrue(new.exists())
        with self.db:self.db.execute("UPDATE clips SET status='archived' WHERE id=?",(cid,))
        purge(self.db,self.root,[cid])
        self.assertFalse(old.exists())
        self.assertFalse(new.exists())
    def test_layout_validation(self):
        ad=dict(width=800,height=200,x=0,y=650,opacity=.8,start=0,end=None)
        spec=validate({'ad_layout':ad,'auto_crop':'0','sub_size':'72'})
        self.assertEqual(spec['ad_layout'],ad)
        self.assertFalse(spec['auto_crop'])
        self.assertEqual(spec['caption_style']['size'],72)
        with self.assertRaises(ValueError):validate({'ad_layout':{**ad,'x':500}})

if __name__=='__main__': unittest.main()
