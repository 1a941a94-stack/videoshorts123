import unittest
from ad_filter import classify

class AdFilterTest(unittest.TestCase):
    def test_promo(self):
        self.assertEqual(classify('Введи промокод TEST'), 'promo_text')
        self.assertEqual(classify('Sponsored by Example'), 'promo_text')
    def test_domain(self):
        self.assertEqual(classify('example.com'), 'domain')
    def test_brand(self):
        self.assertEqual(classify('ExampleBrand', ['ExampleBrand']), 'known_advertiser')
    def test_normal(self):
        self.assertIsNone(classify('Кот смешно упал с дивана'))
