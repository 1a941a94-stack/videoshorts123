import unittest
from clipfactory import select
class Test(unittest.TestCase):
 def test_peaks(self):
  info={'duration':120,'heatmap':[{'start_time':i*10,'end_time':(i+1)*10,'value':v} for i,v in enumerate([.1,.2,.9,.4,.1,.2,.3,.8,.2,.1,.1,.2])]}
  r=select(info,30,3,.7); self.assertEqual(len(r),2); self.assertEqual(r[0]['score'],.9)
 def test_missing(self): self.assertEqual(select({'duration':120}),[])
 def test_short(self): self.assertEqual(select({'duration':10},45),[])
if __name__=='__main__': unittest.main()
