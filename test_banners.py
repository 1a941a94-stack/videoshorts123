import unittest
import tempfile
import json
from pathlib import Path
from banners import Banner,choose

class BannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.image=self.root/'banner.png'
        self.image.touch()
    def test_filter(self):
        f=Banner(self.image,opacity=.5,start=2,end=10).filter(8)
        self.assertIn("aa=0.5",f)
        self.assertIn("lt(t,8)",f)
    def test_invalid_opacity(self):
        with self.assertRaises(ValueError): Banner(self.image,opacity=2)
    def test_expired(self):
        p=self.root/'campaigns.json'
        p.write_text(json.dumps({'campaigns':[{'path':'banner.png','active_until':'2000-01-01T00:00:00Z'},{'path':'banner.png','name':'active'}]}))
        self.assertEqual(choose(p,45).name,'active')
    def test_disabled(self):
        p=self.root/'campaigns.json'
        p.write_text(json.dumps({'campaigns':[{'path':'banner.png','enabled':False}]}))
        with self.assertRaises(ValueError): choose(p,45)
