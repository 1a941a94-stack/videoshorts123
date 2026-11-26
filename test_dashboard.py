import tempfile
import unittest
from dashboard import create_app

class DashboardTest(unittest.TestCase):
    def test_local_and_csrf(self):
        with tempfile.TemporaryDirectory() as folder:
            app=create_app(folder)
            app.testing=True
            client=app.test_client()
            self.assertEqual(client.get('/').status_code,200)
            self.assertEqual(client.post('/sources',data={'query':'test'}).status_code,403)
            with client.session_transaction() as s: csrf=s['csrf']
            self.assertEqual(client.post('/sources',data={'query':'test','csrf':csrf}).status_code,302)
            self.assertIn(b'test',client.get('/').data)
            self.assertEqual(client.get('/',headers={'Host':'example.com'}).status_code,403)
