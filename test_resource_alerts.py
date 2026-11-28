import unittest
from business_reports import resource_alerts
from business_resources import budget_health

class ResourceAlertsTest(unittest.TestCase):
    def test_warning_and_exhaustion(self):
        rows=resource_alerts(dict(budget_health=budget_health([100,1000],[80,1000]),services=[]))
        self.assertEqual([x[0] for x in rows],['budget_warning_daily','budget_monthly'])
    def test_expiry_details(self):
        rows=resource_alerts(dict(budget_health=budget_health([0,0],[0,0]),services=[dict(health='soon',supplier='Host',name='VPS',expiry_date='2026-12-01')]))
        self.assertEqual(rows[0][0],'renewal')
        self.assertIn('VPS',rows[0][1])
