import unittest
from pipeline import connect
from duplicates import compare,store,find_duplicate

def sample(sha='a',duration=20):
    return {'version':1,'sha256':sha,'duration':duration,
            'frames':[[i/12,f'{(i*0x123456789abcdef)&((1<<64)-1):016x}'] for i in range(12)]}

class DuplicatesTest(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(compare(sample(),sample()),('exact',1.0))
    def test_reencoded(self):
        a,b=sample(),sample('b')
        b['frames']=[[t,f'{int(h,16)^3:016x}'] for t,h in b['frames']]
        self.assertEqual(compare(a,b),('visual',1.0))
    def test_different(self):
        a,b=sample(),sample('b')
        b['frames']=[[t,f'{int(h,16)^0xffffffffffffffff:016x}'] for t,h in b['frames']]
        self.assertIsNone(compare(a,b))
    def test_static(self):
        a,b=sample(),sample('b')
        a['frames']=b['frames']=[[i/12,'0000000000000000'] for i in range(12)]
        self.assertIsNone(compare(a,b))
    def test_duration(self):
        self.assertIsNone(compare(sample(),sample('b',30)))
    def test_database(self):
        db=connect(':memory:')
        try:
            with db:
                db.execute("INSERT INTO videos(id,url,status,checked) VALUES('v','https://example.com','ready',0)")
                for i,status in [(1,'done'),(2,'running')]:
                    db.execute("INSERT INTO clips(id,video_id,start,end,score,status,updated,mode) VALUES(?,'v',?,20,1,?,0,'short')",(i,i,status))
                store(db,1,sample())
                store(db,2,sample())
            self.assertEqual(find_duplicate(db,2,sample()),(1,'exact',1.0))
            self.assertIsNone(find_duplicate(db,1,sample()))
        finally: db.close()
