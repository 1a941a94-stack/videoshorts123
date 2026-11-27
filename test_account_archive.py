import unittest
from pipeline import connect
from publishing import init,add_account,enqueue,approve,claim,configure_auto,sync_ready
from account_lifecycle import change,snapshot

class ArchiveTest(unittest.TestCase):
    def test_archive_preserves_history_and_stops_queue(self):
        db=init(connect(':memory:'))
        self.addCleanup(db.close)
        add_account(db,'example','telegram','@example','TEST_TOKEN')
        with db:
            db.execute("INSERT INTO videos(id,url,status,checked) VALUES('example','https://example.invalid','ready',0)")
            for i in range(3):
                db.execute("INSERT INTO clips(video_id,start,end,score,status,updated,production_profile) VALUES('example',?,?,1,'done',0,'test')",(i*6,i*6+6))
            db.execute("UPDATE accounts SET enabled=1,auto_queue=1,production_profile='test'")
        enqueue(db,1,1,'test',0)
        enqueue(db,1,2,'test',0)
        approve(db,2)
        with db:
            db.execute("UPDATE publications SET status='sent' WHERE id=1")
        change(db,1,'archive')
        self.assertEqual(snapshot(db)['counts']['archived'],1)
        self.assertEqual(tuple(db.execute('SELECT enabled,auto_queue FROM accounts').fetchone()),(0,0))
        self.assertEqual([r[0] for r in db.execute('SELECT status FROM publications ORDER BY id')],['sent','cancelled'])
        with self.assertRaises(ValueError): change(db,1,'verify')
        with self.assertRaises(ValueError): enqueue(db,1,3,'test',0)
        with self.assertRaises(ValueError): configure_auto(db,1,'test','',60,True)
        with db: db.execute('UPDATE accounts SET enabled=1,auto_queue=1')
        self.assertEqual(sync_ready(db,100),0)
        self.assertIsNone(claim(db,100))
