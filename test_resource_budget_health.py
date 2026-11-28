import unittest
from business_resources import budget_health

class ResourceBudgetHealthTest(unittest.TestCase):
    def test_unlimited(self):
        self.assertEqual(budget_health([0],[500])[0],dict(remaining=None,percent=None,warning=False,exhausted=False))
    def test_threshold(self):
        self.assertFalse(budget_health([100],[79])[0]['warning'])
        self.assertTrue(budget_health([100],[80])[0]['warning'])
        self.assertEqual(budget_health([100],[80])[0]['remaining'],20)
    def test_exhaustion(self):
        row=budget_health([100],[120])[0]
        self.assertEqual(row['remaining'],0)
        self.assertTrue(row['exhausted'])
        self.assertEqual(row['percent'],120)
