import unittest
from pipeline import connect
from publishing import init,add_account,reconcile_youtube

class YouTubeReconcileTest(unittest.TestCase):
    def test_public_confirmation_and_no_change_on_network_failure(self):
        db=init(connect(':memory:'))
        self.addCleanup(db.close)
        add_account(db,'yt','youtube','UC'+'a'*22,'TEST_TOKEN')
        with db:
            db.execute("INSERT INTO videos(id,url,status,checked) VALUES('source','local','ready',0)")
            db.execute("INSERT INTO clips(video_id,start,end,score,status,updated) VALUES('source',0,10,1,'done',0)")
            db.execute("INSERT INTO publications(account_id,clip_id,caption,scheduled,status,updated,remote_id) VALUES(1,1,'',0,'uploaded_private',0,'abcdefghijk')")
        reconcile_youtube(db,'.',1,lambda *args:('public','OK'))
        self.assertEqual(db.execute('SELECT status FROM publications').fetchone()[0],'sent')
        def fail(*args): raise RuntimeError()
        reconcile_youtube(db,'.',1,fail)
        self.assertEqual(db.execute('SELECT status FROM publications').fetchone()[0],'sent')
        reconcile_youtube(db,'.',1,lambda *args:('private','Private'))
        self.assertEqual(db.execute('SELECT status FROM publications').fetchone()[0],'uploaded_private')
