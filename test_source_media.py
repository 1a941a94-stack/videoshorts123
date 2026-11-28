import unittest
import tempfile
from pathlib import Path
from filelock import FileLock
from source_media import boundaries,prune_cache,speech_edges

class SourceMediaTest(unittest.TestCase):
    def test_pause(self):
        self.assertEqual(boundaries(10,55,30,100,[8,62]),(8,62,'pause'))
    def test_sentence(self):
        self.assertEqual(boundaries(10,55,30,100,[9,56],[8,64]),(8,64,'sentence'))
    def test_peak(self):
        a,b,_=boundaries(10,55,11,100,[14,65])
        self.assertLessEqual(a,11)
        self.assertGreaterEqual(b,11)
    def test_no_boundaries(self):
        self.assertEqual(boundaries(10,55,30,100,[]),(10,55,'unadjusted'))
    def test_separate_sentence_edges(self):
        a,b,method=boundaries(10,55,30,100,[],sentence_starts=[9,58],sentence_ends=[11,60])
        self.assertEqual((a,b,method),(9,60,'sentence'))
    def test_cut_inside_word_is_avoided(self):
        self.assertEqual(boundaries(10,55,30,100,[9,58],words=[(8,10),(54,56)]),(10,58,'pause'))
    def test_padding_respects_next_word(self):
        starts,ends,words=speech_edges([(0,1,'End.'),(1.04,2,'Next')],10,20)
        self.assertAlmostEqual(ends[0],11.02)
        self.assertAlmostEqual(starts[0],11.02)
    def test_cache_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            active=root/'active.mp4'
            inactive=root/'inactive.mp4'
            active.write_bytes(b'a')
            inactive.write_bytes(b'b')
            with FileLock(str(root/'active.lock')):
                prune_cache(root,max_bytes=0)
                self.assertTrue(active.exists())
                self.assertFalse(inactive.exists())
