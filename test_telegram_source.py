import unittest
from telegram_source import channel_name

class TelegramSourceTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(channel_name('@FunnyVideos'),'funnyvideos')
        self.assertEqual(channel_name('https://t.me/FunnyVideos/'),'funnyvideos')
    def test_invalid(self):
        for value in ('https://example.com/test','https://t.me/+secret','../secret','https://t.me/channel/123'):
            with self.assertRaises(ValueError):
                channel_name(value)
