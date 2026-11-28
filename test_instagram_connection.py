import os
import sqlite3
import unittest
from unittest.mock import patch, Mock
from account_sessions import check_connection, save_check

class InstagramConnectionTest(unittest.TestCase):
    def test_invalid_token_pauses_account(self):
        account=dict(platform='instagram',destination='123456',token_env='TEST_META_TOKEN')
        response=Mock(ok=False)
        response.json.return_value={'error':{'code':190}}
        with patch.dict(os.environ,{'TEST_META_TOKEN':'example','CLIP_META_API_VERSION':'v26.0'}), patch('requests.get',return_value=response):
            ok,detail=check_connection('.',account)
        self.assertFalse(ok)
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE accounts(id INTEGER PRIMARY KEY, enabled INTEGER)')
            db.execute('INSERT INTO accounts VALUES(1,1)')
            save_check(db,1,ok,detail)
            self.assertEqual(db.execute('SELECT enabled FROM accounts').fetchone()[0],0)
    def test_network_failure_does_not_pause(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE accounts(id INTEGER PRIMARY KEY, enabled INTEGER)')
            db.execute('INSERT INTO accounts VALUES(1,1)')
            save_check(db,1,False,'Network error')
            self.assertEqual(db.execute('SELECT enabled FROM accounts').fetchone()[0],1)
