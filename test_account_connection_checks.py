import sqlite3
import unittest
from unittest.mock import patch
from account_sessions import save_check,decorate_checks


class ConnectionChecksTest(unittest.TestCase):
    def test_latest_failure_preserves_success(self):
        db=sqlite3.connect(':memory:')
        db.row_factory=sqlite3.Row
        self.addCleanup(db.close)
        db.execute('CREATE TABLE accounts(id INTEGER PRIMARY KEY)')
        db.execute('INSERT INTO accounts VALUES(1)')
        with patch('time.time',return_value=100):
            save_check(db,1,True,'OK')
        with patch('time.time',return_value=200):
            save_check(db,1,False,'Unavailable')
        row=db.execute('SELECT * FROM account_connection_checks').fetchone()
        self.assertEqual((row['checked'],row['last_success'],row['ok']),(200,100,0))
        accounts=decorate_checks(db,[{'id':1},{'id':2}])
        self.assertFalse(accounts[0]['connection_check']['ok'])
        self.assertIsNone(accounts[1]['connection_check'])
