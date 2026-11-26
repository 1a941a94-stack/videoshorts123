import unittest
import tempfile
from short_templates import validate,save,load

class TemplateTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(validate({})['size'],960)
    def test_outside_canvas(self):
        with self.assertRaises(ValueError): validate({'size':1000,'x':100})
    def test_invalid_background(self):
        with self.assertRaises(ValueError): validate({'background':'../secret.jpg'})
    def test_persistence(self):
        with tempfile.TemporaryDirectory() as root:
            spec=save(root,'meme_01',{'size':800,'border':8,'fit':'cover'})
            self.assertEqual(load(root)['meme_01'],spec)
