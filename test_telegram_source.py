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

    def test_library_dedup(self):
        from pipeline import connect
        from telegram_source import add_channels
        db=connect(':memory:')
        try:
            add_channels(db,['@FunnyVideos','https://t.me/FunnyVideos','@OtherVideos'],50,200)
            add_channels(db,['@FunnyVideos'],100,1000)
            rows=db.execute('SELECT * FROM telegram_channels ORDER BY name').fetchall()
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['history'],50)
            self.assertEqual(rows[0]['min_views'],200)
            self.assertIsNone(rows[0]['cursor'])
        finally: db.close()
