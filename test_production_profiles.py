import unittest
import tempfile
from production_profiles import save,load

class ProductionProfilesTest(unittest.TestCase):
    def test_save(self):
        with tempfile.TemporaryDirectory() as root:
            p=save(root,'meme_1',{'template':'circle','campaign':'ad','captions':'1'}, {'circle':{}}, ['ad'])
            self.assertEqual(load(root)['meme_1'],p)
            self.assertTrue(p['captions'])
    def test_invalid(self):
        with tempfile.TemporaryDirectory() as root:
            for name,form in [('../bad',{'template':'circle'}),('good',{'template':'missing'}),('good',{'template':'circle','campaign':'missing'})]:
                with self.assertRaises(ValueError): save(root,name,form,{'circle':{}},[])
