import unittest
from highlights import select, align

class HighlightsTest(unittest.TestCase):
    def test_plateau(self):
        info={'duration':100,'heatmap':[dict(start_time=i*10,end_time=(i+1)*10,value=v) for i,v in enumerate([.1,.2,.9,.9,.2,.1])]}
        result=select(info,30)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['peak'],30)
    def test_alignment(self):
        self.assertEqual(align(10,55,30,[8,57],100),(8,57))
    def test_peak_preserved(self):
        a,b=align(10,40,11,[12,42],100)
        self.assertLessEqual(a,11)
        self.assertGreaterEqual(b,11)
    def test_invalid_data(self):
        self.assertEqual(select({'duration':100,'heatmap':[{},dict(start_time=1,end_time=2,value=float('nan'))]}),[])
