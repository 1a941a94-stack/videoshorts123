import unittest
from captions import ass,stamp,clean
class CaptionTest(unittest.TestCase):
    def test_timing(self):
        self.assertEqual(stamp(61.25),'0:01:01.25')
    def test_highlight(self):
        s=ass([(0,.5,'Привет'),(.5,1,'мир')])
        self.assertIn(r'{\c&H00D5FF&}Привет',s)
        self.assertEqual(s.count('Dialogue:'),2)
    def test_escape(self):
        self.assertEqual(clean(r'{\pos(0,0)}'),'(／pos(0,0))')
    def test_empty(self):
        self.assertNotIn('Dialogue:',ass([]))
    def test_invalid_color(self):
        with self.assertRaises(ValueError): ass([],highlight='invalid')
