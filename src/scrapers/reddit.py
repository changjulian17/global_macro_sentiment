"""Reddit scraper — uses the public Reddit JSON API (no API key required).

Reads hot posts from macro/finance subreddits.  Reddit rate-limits to roughly
1 request per 2 seconds for unauthenticated clients; we sleep between calls.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

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

_HEADERS = {
    # Reddit requires a descriptive User-Agent for the public JSON API.
    "User-Agent": "MacroSentimentBot/1.0 (personal research; no login)"
}


def fetch_subreddit(subreddit: str, limit: int = 25) -> list:
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        if resp.status_code == 429:
            logger.warning("Reddit rate-limited on r/%s — skipping", subreddit)
            return []
        if resp.status_code != 200:
            logger.warning("Reddit r/%s: HTTP %d", subreddit, resp.status_code)
            return []
        children = resp.json().get("data", {}).get("children", [])
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
                    "score": p.get("score", 0),      # upvotes — not sentiment score
                    "num_comments": p.get("num_comments", 0),
                    "url": "https://reddit.com" + p.get("permalink", ""),
                    "published": datetime.fromtimestamp(
                        p.get("created_utc", 0), tz=timezone.utc
                    ).isoformat(),
                }
            )
        return posts
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
