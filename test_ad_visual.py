import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
from ad_visual import VisualAds

class VisualAdsTest(unittest.TestCase):
    def test_embedded_and_scaled(self):
        rng=np.random.default_rng(42)
        template=rng.integers(0,256,(48,96),dtype=np.uint8)
        with tempfile.TemporaryDirectory() as folder:
            cv2.imwrite(str(Path(folder)/'sample.png'),template)
            detector=VisualAds(folder)
            for scale in (1.,.5,1.4):
                frame=np.zeros((240,320),dtype=np.uint8)
                img=cv2.resize(template,(round(96*scale),round(48*scale)),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
                h,w=img.shape
                frame[30:30+h,40:40+w]=img
                match=detector.match(cv2.cvtColor(frame,cv2.COLOR_GRAY2BGR))
                self.assertIsNotNone(match)
                self.assertEqual(match[0],'sample')
            blank=np.zeros((240,320,3),dtype=np.uint8)
            self.assertIsNone(detector.match(blank))
    def test_empty_library(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(VisualAds(folder).match(np.zeros((100,100,3),dtype=np.uint8)))
