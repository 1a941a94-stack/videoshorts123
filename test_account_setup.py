import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dashboard import create_app
from pipeline import connect

class AccountSetupTest(unittest.TestCase):
    def test_wizard_activation_requires_verified_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'production-profiles.json').write_text('{"short":{}}',encoding='utf-8')
            app=create_app(root)
            app.testing=True
            with app.test_client() as client:
                self.assertEqual(client.get('/business/accounts/setup').status_code,200)
                with client.session_transaction() as sess: csrf=sess['csrf']
                form=dict(csrf=csrf,name='test',platform='telegram',destination='@test',token_env='TEST_TOKEN')
                response=client.post('/business/accounts/setup',data=form)
                self.assertEqual(response.status_code,303)
                self.assertEqual(client.get(response.location).status_code,200)
                settings=dict(csrf=csrf,profile='short',confirm='1',interval='3600')
                route='/business/accounts/setup/1/activate'
                client.post(route,data=settings)
                db=connect(root/'clipfactory.sqlite3')
                try: self.assertEqual(db.execute('SELECT enabled FROM accounts').fetchone()[0],0)
                finally: db.close()
                with patch('account_sessions.check_connection',return_value=(True,'OK')):
                    self.assertEqual(client.post('/business/accounts/setup/1/check',data={'csrf':csrf}).status_code,303)
                client.post(route,data=settings)
                db=connect(root/'clipfactory.sqlite3')
                try:
                    self.assertEqual(tuple(db.execute('SELECT enabled,auto_queue,production_profile FROM accounts').fetchone()),(1,1,'short'))
                finally: db.close()
