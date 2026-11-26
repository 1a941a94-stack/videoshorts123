import unittest
from pipeline import connect
from publishing import init,add_account,enqueue,approve,claim,measure,sync_ready,configure_auto
class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.db=init(connect(':memory:'))
        self.addCleanup(self.db.close)
        self.db.execute("INSERT INTO videos(id,url,status,checked) VALUES ('abc','https://example.com','ready',0)")
        for i in range(2):
            self.db.execute("INSERT INTO clips(video_id,start,end,score,status,updated) VALUES ('abc',?,?,.9,'done',0)",(i*50,i*50+45))
        self.db.commit()
        add_account(self.db,'test','telegram','@test','TEST_TOKEN',daily_limit=1)
    def test_approval(self):
        enqueue(self.db,1,1,'test',100)
        enqueue(self.db,1,1,'test',100)
        self.assertEqual(self.db.execute('SELECT count(*) FROM publications').fetchone()[0],1)
        self.assertIsNone(claim(self.db,100))
        approve(self.db,1)
        self.assertIsNone(claim(self.db,100))
        with self.db: self.db.execute('UPDATE accounts SET enabled=1')
        self.assertIsNone(claim(self.db,99))
        self.assertEqual(claim(self.db,100)['id'],1)
    def test_limit(self):
        with self.db: self.db.execute('UPDATE accounts SET enabled=1')
        for i in (1,2):
            enqueue(self.db,1,i,'test',100)
            approve(self.db,i)
        self.assertIsNotNone(claim(self.db,100))
        with self.db: self.db.execute("UPDATE publications SET status='sent',updated=100 WHERE id=1")
        self.assertIsNone(claim(self.db,4000))
        measure(self.db,1,100,80,20)
        self.assertEqual(self.db.execute('SELECT revenue_kopecks FROM measurements').fetchone()[0],20)
    def test_automatic_queue(self):
        with self.db:
            self.db.execute("UPDATE clips SET production_profile='alpha' WHERE id=1")
            self.db.execute("UPDATE accounts SET enabled=1")
        configure_auto(self.db,1,'alpha','caption',60,True)
        self.assertEqual(sync_ready(self.db,100),1)
        self.assertEqual(sync_ready(self.db,100),0)
        row=claim(self.db,100)
        self.assertEqual(row['clip_id'],1)
        self.assertEqual(row['caption'],'caption')
    def test_blocked_pauses_account(self):
        with self.db: self.db.execute('UPDATE accounts SET enabled=1')
        for i in (1,2):
            enqueue(self.db,1,i,'test',100)
            approve(self.db,i)
        self.assertIsNotNone(claim(self.db,100))
        with self.db: self.db.execute("UPDATE publications SET status='blocked' WHERE id=1")
        self.assertIsNone(claim(self.db,100))
