import unittest
from framing import composition

class FramingTest(unittest.TestCase):
    def test_single(self):
        c=composition(1920,1080,[(850,150,200,200)])
        self.assertIsNotNone(c)
        w,h,x,y=c
        self.assertLessEqual(x,850)
        self.assertGreaterEqual(x+w,1050)
        self.assertLessEqual(x+w,1920)
    def test_wide_group(self):
        self.assertIsNone(composition(1920,1080,[(100,100,100,100),(1600,100,100,100)]))
    def test_no_face(self):
        self.assertIsNone(composition(1920,1080,[]))
    def test_edge(self):
        self.assertEqual(composition(1920,1080,[(0,50,100,100)])[2],0)
