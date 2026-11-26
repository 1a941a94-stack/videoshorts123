import unittest
from types import SimpleNamespace as NS
from telegram_discovery import qualifies

def msg(video=True,duration=20,size=1000,protected=False):
    return NS(action=None,video=video,noforwards=protected,file=NS(duration=duration,size=size))

class DiscoveryTest(unittest.TestCase):
    def test_eligible(self):
        self.assertEqual(qualifies([msg() for _ in range(6)]+[msg(False) for _ in range(24)]),(30,6,True))
    def test_too_few(self):
        self.assertEqual(qualifies([msg() for _ in range(4)]),(4,4,False))
    def test_protected_or_long(self):
        self.assertEqual(qualifies([msg(protected=True),msg(duration=100),msg(size=200*1024**2)]),(3,0,False))
    def test_empty(self):
        self.assertEqual(qualifies([]),(0,0,False))
