import os
import unittest
from unittest.mock import Mock, patch

from src.scrapers import reddit


def _payload(title: str = "Post title"):
    return {
        "data": {
            "children": [
                {
                    "data": {
                        "title": title,
                        "selftext": "Body text",
                        "score": 42,
                        "num_comments": 7,
                        "permalink": "/r/investing/comments/abc123/post_title/",
                        "created_utc": 1710000000,
                    }
                }
            ]
        }
    }


class TestRedditScraper(unittest.TestCase):
    def setUp(self):
        reddit._OAUTH_TOKEN = None
        reddit._OAUTH_TOKEN_EXPIRES_AT = 0.0
        reddit._PUBLIC_403_HINT_LOGGED = False

    def test_fetch_subreddit_uses_oauth_when_credentials_exist(self):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=None)

        token_resp = Mock(status_code=200)
        token_resp.json.return_value = {"access_token": "token-123", "expires_in": 3600}

        listing_resp = Mock(status_code=200)
        listing_resp.json.return_value = _payload()

        session.post.return_value = token_resp
        session.get.return_value = listing_resp

        with patch.dict(
            os.environ,
            {"REDDIT_CLIENT_ID": "client-id", "REDDIT_CLIENT_SECRET": "client-secret"},
            clear=False,
        ):
            with patch("src.scrapers.reddit.requests.Session", return_value=session):
                posts = reddit.fetch_subreddit("investing", limit=1)

        self.assertEqual(1, len(posts))
        self.assertEqual("Post title. Body text", posts[0]["text"])
        self.assertEqual("https://reddit.com/r/investing/comments/abc123/post_title/", posts[0]["url"])
        self.assertEqual("https://www.reddit.com/api/v1/access_token", session.post.call_args.args[0])
        self.assertEqual("https://oauth.reddit.com/r/investing/hot", session.get.call_args.args[0])
        self.assertEqual("bearer token-123", session.get.call_args.kwargs["headers"]["Authorization"])

    def test_fetch_subreddit_falls_back_after_public_api_403(self):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=None)

        first = Mock(status_code=403)
        second = Mock(status_code=200)
        second.json.return_value = _payload("Fallback title")
        session.get.side_effect = [first, second]

        with patch.dict(os.environ, {}, clear=True):
            with patch("src.scrapers.reddit.requests.Session", return_value=session):
                posts = reddit.fetch_subreddit("investing", limit=1)

        self.assertEqual(1, len(posts))
        self.assertEqual("Fallback title. Body text", posts[0]["text"])
        self.assertEqual(2, session.get.call_count)
        self.assertEqual("https://api.reddit.com/r/investing/hot", session.get.call_args_list[0].args[0])
        self.assertEqual("https://www.reddit.com/r/investing/hot.json", session.get.call_args_list[1].args[0])

    def test_fetch_subreddit_logs_hint_when_public_endpoints_reject_requests(self):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=None)
        session.get.side_effect = [Mock(status_code=403), Mock(status_code=403)]

        with patch.dict(os.environ, {}, clear=True):
            with patch("src.scrapers.reddit.requests.Session", return_value=session):
                with patch.object(reddit.logger, "warning") as warn:
                    posts = reddit.fetch_subreddit("investing", limit=1)

        self.assertEqual([], posts)
        joined = "\n".join(str(call.args[0]) for call in warn.call_args_list)
        self.assertIn("GitHub Actions", joined)


if __name__ == "__main__":
    unittest.main()