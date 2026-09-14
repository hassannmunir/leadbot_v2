import unittest

from leadbot.app.progress import format_duration


class ProgressTests(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(0), "0s")
        self.assertEqual(format_duration(65), "1m 5s")
        self.assertEqual(format_duration(3661), "1h 1m 1s")


if __name__ == "__main__":
    unittest.main()
