import sqlite3
import unittest
from unittest.mock import patch
from proxy6_inventory import init,state

class InventoryHealthTest(unittest.TestCase):
    def test_inventory_health(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.row_factory=sqlite3.Row
        init(db)
        now=2000000
        db.executemany('INSERT INTO proxy6_inventory VALUES(?,?,?,?,?)',[
            ('1',4,'de',now-1,1),('2',4,'de',now+100,0),
            ('3',4,'de',now+100,1),('4',4,'de',now+800000,1)])
        db.execute("INSERT INTO proxy6_snapshot VALUES(1,'10','USD',?)",(now-86400,))
        with patch('proxy6_inventory.time.time',return_value=now):
            info=state(db)
        self.assertEqual((info['total'],info['active'],info['soon'],info['expired'],info['inactive']),(4,2,1,1,1))
        self.assertTrue(info['stale'])
        self.assertEqual([x['health'] for x in info['details']],['expired','inactive','soon','active'])
