"""Compile every Jinja template and exercise business routes on a fresh database."""
import tempfile
import unittest
from pathlib import Path
from dashboard import create_app

class BusinessTemplateTest(unittest.TestCase):
    def test_all_templates_compile(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(Path(folder))
            for name in app.jinja_env.list_templates():
                with self.subTest(template=name):
                    app.jinja_env.get_template(name)

    def test_business_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(Path(folder))
            app.testing = True
            with app.test_client() as client:
                for path in ('/', '/business', '/business/accounts', '/business/calendar',
                             '/business/monetization', '/business/finance', '/business/analytics',
                             '/business/reports', '/business/resources', '/business/library', '/publishing'):
                    with self.subTest(path=path):
                        self.assertEqual(client.get(path).status_code, 200)
