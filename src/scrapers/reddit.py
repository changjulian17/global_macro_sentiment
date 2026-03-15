"""Reddit scraper.

Prefers Reddit OAuth when credentials are available and otherwise falls back to
public JSON endpoints. GitHub-hosted runners are more likely to receive 403s on
unauthenticated requests, so CI should provide Reddit API credentials via:

- REDDIT_CLIENT_ID
- REDDIT_CLIENT_SECRET
- optional REDDIT_USER_AGENT
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

_OAUTH_TOKEN: str | None = None
_OAUTH_TOKEN_EXPIRES_AT = 0.0
_PUBLIC_403_HINT_LOGGED = False

SUBREDDITS = [
    "investing",
    "stocks",
    "wallstreetbets",
    "Economics",
    "MacroEconomics",
    "SecurityAnalysis",
    "StockMarket",
    "GlobalMarkets",
    "worldnews",
    "finance",
]

_DEFAULT_USER_AGENT = os.getenv(
    "REDDIT_USER_AGENT",
    "MacroSentimentBot/1.1 (research automation; contact repo maintainer)",
)
_PUBLIC_HEADERS = {
    "Accept": "application/json",
    "User-Agent": _DEFAULT_USER_AGENT,
}


def _oauth_credentials() -> tuple[str, str] | None:
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return client_id, client_secret
    return None


def _get_oauth_token(session: requests.Session) -> str | None:
    global _OAUTH_TOKEN, _OAUTH_TOKEN_EXPIRES_AT

    creds = _oauth_credentials()
    if creds is None:
        return None

    now = time.time()
    if _OAUTH_TOKEN and now < (_OAUTH_TOKEN_EXPIRES_AT - 60):
        return _OAUTH_TOKEN

    resp = session.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=creds,
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": _DEFAULT_USER_AGENT},
        timeout=12,
    )
    if resp.status_code != 200:
        logger.warning("Reddit OAuth token request failed: HTTP %d", resp.status_code)
        return None

    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        logger.warning("Reddit OAuth token request failed: missing access token")
        return None

    _OAUTH_TOKEN = token
    _OAUTH_TOKEN_EXPIRES_AT = now + int(payload.get("expires_in", 3600))
    return _OAUTH_TOKEN


def _fetch_listing(session: requests.Session, subreddit: str, limit: int) -> list:
    global _PUBLIC_403_HINT_LOGGED

    token = _get_oauth_token(session)
    endpoints: list[tuple[str, str, dict[str, str]]] = []

    if token:
        endpoints.append(
            (
                "oauth",
                f"https://oauth.reddit.com/r/{subreddit}/hot",
                {"Authorization": f"bearer {token}"},
            )
        )

    endpoints.extend(
        [
            ("public-api", f"https://api.reddit.com/r/{subreddit}/hot", {}),
            ("public-web", f"https://www.reddit.com/r/{subreddit}/hot.json", {}),
        ]
    )

    saw_public_403 = False
    saw_rate_limit = False

    for label, url, extra_headers in endpoints:
        resp = session.get(
            url,
            params={"limit": limit, "raw_json": 1},
            headers={**_PUBLIC_HEADERS, **extra_headers},
            timeout=12,
        )

        if resp.status_code == 200:
            return resp.json().get("data", {}).get("children", [])

        if resp.status_code == 429:
            saw_rate_limit = True
            logger.warning("Reddit rate-limited on r/%s via %s", subreddit, label)
            continue

        if resp.status_code == 403:
            if label != "oauth":
                saw_public_403 = True
            logger.warning("Reddit r/%s via %s: HTTP 403", subreddit, label)
            continue

        logger.warning("Reddit r/%s via %s: HTTP %d", subreddit, label, resp.status_code)

    if saw_public_403 and token is None and not _PUBLIC_403_HINT_LOGGED:
        logger.warning(
            "Reddit public endpoints are rejecting this environment. "
            "For GitHub Actions, add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET secrets."
        )
        _PUBLIC_403_HINT_LOGGED = True

    if saw_rate_limit:
        return []

    return []


def _normalize_posts(children: list, subreddit: str) -> list:
    posts = []
    for child in children:
        p = child.get("data", {})
        title = p.get("title", "")
        selftext = p.get("selftext", "")
        if selftext in ("[removed]", "[deleted]", ""):
            text = title
        else:
            text = title + ". " + selftext[:400]

        posts.append(
            {
                "source": subreddit,
                "title": title,
                "text": text,
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "url": "https://reddit.com" + p.get("permalink", ""),
                "published": datetime.fromtimestamp(
                    p.get("created_utc", 0), tz=timezone.utc
                ).isoformat(),
            }
        )
    return posts


def fetch_subreddit(subreddit: str, limit: int = 25) -> list:
    try:
        with requests.Session() as session:
            children = _fetch_listing(session, subreddit, limit)
        return _normalize_posts(children, subreddit)
    except Exception as exc:
        logger.warning("Reddit r/%s error: %s", subreddit, exc)
        return []


def fetch_all() -> list:
    all_posts: list = []
    for subreddit in SUBREDDITS:
        posts = fetch_subreddit(subreddit)
        logger.info("  r/%s: %d posts", subreddit, len(posts))
        all_posts.extend(posts)
        time.sleep(2.0)  # stay well under rate limit
    logger.info("Reddit total: %d posts", len(all_posts))
    return all_posts
