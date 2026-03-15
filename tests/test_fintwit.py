import unittest
from unittest.mock import Mock, patch

from src.scrapers import fintwit


class TestFinTwitScraper(unittest.TestCase):
    def test_try_instance_parses_rss_entries(self):
        rss = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<rss version=\"2.0\"><channel>
<item>
  <title>First tweet</title>
  <link>https://x.com/tester/status/1</link>
  <description><![CDATA[<p>Risk assets <b>rallying</b> today</p>]]></description>
  <pubDate>Sat, 14 Mar 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title>Second tweet</title>
  <link>https://x.com/tester/status/2</link>
  <description><![CDATA[<div>Dollar strong, watch yields</div>]]></description>
  <pubDate>Sat, 14 Mar 2026 11:00:00 GMT</pubDate>
</item>
</channel></rss>"""

        fake_resp = Mock(status_code=200, content=rss)
        with patch("src.scrapers.fintwit.requests.get", return_value=fake_resp):
            posts = fintwit._try_instance("https://nitter.example", "tester")

        self.assertIsNotNone(posts)
        assert posts is not None
        self.assertEqual(2, len(posts))
        self.assertEqual("tester", posts[0]["username"])
        self.assertEqual("tester", posts[0]["source"])
        self.assertIn("Risk assets", posts[0]["text"])
        self.assertNotIn("<b>", posts[0]["text"])
        self.assertEqual("https://x.com/tester/status/1", posts[0]["url"])
        self.assertTrue(posts[0]["published"].startswith("2026-03-14T10:00:00"))

        print("Sample parsed tweets:")
        for idx, post in enumerate(posts[:2], start=1):
            print(f"  {idx}. @{post['source']}: {post['text']}")

    def test_try_instance_non_200_returns_none(self):
        fake_resp = Mock(status_code=503, content=b"")
        with patch("src.scrapers.fintwit.requests.get", return_value=fake_resp):
            posts = fintwit._try_instance("https://nitter.example", "tester")
        self.assertIsNone(posts)

    def test_fetch_account_tries_working_instance_first_then_falls_back(self):
        call_order = []

        def fake_try(instance, username):
            call_order.append(instance)
            if instance == "https://i2":
                return None
            if instance == "https://i1":
                return [{"source": username, "text": "ok"}]
            return None

        with patch.object(fintwit, "NITTER_INSTANCES", ["https://i1", "https://i2", "https://i3"]):
            with patch("src.scrapers.fintwit._try_instance", side_effect=fake_try):
                with patch("src.scrapers.fintwit.time.sleep", return_value=None):
                    posts, chosen = fintwit.fetch_account("tester", working_instance="https://i2")

        self.assertEqual(["https://i2", "https://i1"], call_order)
        self.assertEqual("https://i1", chosen)
        self.assertEqual(1, len(posts))

    def test_fetch_all_skips_inactive_accounts(self):
        accounts = [
            {"username": "active_one", "active": True},
            {"username": "inactive_one", "active": False},
            {"username": "default_active"},
        ]

        def fake_fetch_account(username, working_instance=None):
            return ([{"source": username, "text": "tweet"}], working_instance or "https://i1")

        with patch("src.scrapers.fintwit.fetch_account", side_effect=fake_fetch_account) as mocked:
            with patch("src.scrapers.fintwit.time.sleep", return_value=None):
                posts = fintwit.fetch_all(accounts)

        called_usernames = [call.args[0] for call in mocked.call_args_list]
        self.assertEqual(["active_one", "default_active"], called_usernames)
        self.assertEqual(2, len(posts))

    def test_live_latest_tweet_lyn_alden(self):
        """Live network test: fetch and print Lyn Alden's latest tweet.

        This test depends on public Nitter instance availability and can be
        skipped if all instances are unreachable.
        """
        posts, instance = fintwit.fetch_account("LynAldenContact")
        if not posts:
            self.skipTest("No tweets returned (Nitter instances may be unavailable right now).")

        latest = posts[0]
        print("Latest Lyn Alden tweet:")
        print(f"  Instance: {instance}")
        print(f"  Published: {latest.get('published', '')}")
        print(f"  Text: {latest.get('text', '')}")
        print(f"  URL: {latest.get('url', '')}")

        self.assertEqual("LynAldenContact", latest.get("source"))
        self.assertTrue(
            latest.get("text", "").strip() or latest.get("url", "").strip(),
            "Expected tweet text or URL from live RSS entry.",
        )


if __name__ == "__main__":
    unittest.main()
