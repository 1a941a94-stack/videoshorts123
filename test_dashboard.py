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

    def test_live_status_idle(self):
        with tempfile.TemporaryDirectory() as folder:
            app=create_app(folder)
            app.testing=True
            response=app.test_client().get('/api/job-status')
            self.assertEqual(response.status_code,200)
            self.assertFalse(response.json['running'])
            self.assertIsNone(response.json['result'])
            self.assertEqual(response.json['stats']['videos'],0)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
