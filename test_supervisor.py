import unittest
from pipeline import connect
from supervisor import remaining,recover,retry,day_start

class SupervisorTest(unittest.TestCase):
    def setUp(self):
        self.db=connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute("INSERT INTO videos(id,url,status,checked) VALUES ('abc','https://example.com','ready',0)")
        self.db.commit()
    def insert(self,status,attempts,start=0,updated=None):
        self.db.execute("INSERT INTO clips(video_id,start,end,score,status,attempts,updated) VALUES ('abc',?,?,?,?,?,?)",(start,start+45,.9,status,attempts,day_start() if updated is None else updated))
        self.db.commit()
    def test_daily(self):
        self.insert('done',1)
        self.insert('done',1,50,day_start()-1)
        self.assertEqual(remaining(self.db,3),2)
    def test_recovery(self):
        self.insert('running',1)
        self.insert('running',3,50)
        recover(self.db)
        self.assertEqual([r[0] for r in self.db.execute('SELECT status FROM clips ORDER BY id')],['pending','failed'])
    def test_retry(self):
        self.insert('failed',1,updated=0)
        retry(self.db)
        self.assertEqual(self.db.execute('SELECT status FROM clips').fetchone()[0],'pending')
