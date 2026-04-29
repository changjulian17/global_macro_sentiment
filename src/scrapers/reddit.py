"""Reddit scraper — RSS-only, no API key needed.

Uses Reddit's public RSS feeds (hot/.rss) which are freely accessible without
authentication. Works reliably in GitHub Actions and other CI environments
where the JSON API often returns HTTP 403.

Output schema matches the original JSON API scraper for backward compat:
    { source, title, text, score, num_comments, url, published }
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import feedparser
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

_USER_AGENT = "MacroSentimentBot/1.2 (RSS; research automation)"
_RSS_URL = "https://www.reddit.com/r/{subreddit}/hot/.rss"

# Strip HTML tags from RSS summary content
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_html(raw: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    cleaned = _HTML_TAG_RE.sub(" ", raw)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def _parse_published(published_str: str) -> str:
    """Parse RSS published string to ISO 8601 UTC timestamp.

    feedparser returns a time.struct_time which we convert cleanly.
    """
    try:
        import time as _time

        parsed = feedparser._parse_date(published_str)
        if parsed:
            return datetime(
                parsed.tm_year, parsed.tm_mon, parsed.tm_mday,
                parsed.tm_hour, parsed.tm_min, parsed.tm_sec,
                tzinfo=timezone.utc,
            ).isoformat()
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat()


def fetch_subreddit(subreddit: str, limit: int = 25) -> list:
    """Fetch hot posts from a single subreddit via RSS."""
    url = _RSS_URL.format(subreddit=subreddit)

    try:
        feed = feedparser.parse(url, agent=_USER_AGENT)
    except Exception as exc:
        logger.warning("Reddit r/%s RSS parse error: %s", subreddit, exc)
        return []

    status = feed.get("status", 0)
    if status != 200:
        logger.warning("Reddit r/%s RSS returned HTTP %d", subreddit, status)
        return []

    posts = []
    for entry in feed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        summary_html = entry.get("summary") or entry.get("content", [{}])[0].get("value", "")
        summary_text = _clean_html(summary_html)

        # Build text field: prefer summary, fall back to title
        if summary_text and summary_text != title:
            text = f"{title}. {summary_text[:400]}"
        else:
            text = title

        link = ""
        for link_el in entry.get("links", []):
            if link_el.get("rel") == "alternate" or not link:
                href = link_el.get("href", "")
                if href:
                    link = href

        published_str = entry.get("published", "") or entry.get("updated", "")
        published = _parse_published(published_str) if published_str else datetime.now(timezone.utc).isoformat()

        posts.append(
            {
                "source": subreddit,
                "title": title,
                "text": text,
                "score": 0,
                "num_comments": 0,
                "url": link,
                "published": published,
            }
        )

    return posts


def fetch_all() -> list:
    """Fetch hot posts from all configured subreddits.

    Works identically in GitHub Actions, local dev, and any CI — no
    API credentials, no OAuth, no env vars required.
    """
    all_posts: list = []
    for subreddit in SUBREDDITS:
        posts = fetch_subreddit(subreddit)
        logger.info("  r/%s: %d posts", subreddit, len(posts))
        all_posts.extend(posts)
        time.sleep(2.0)  # rate limit courtesy
    logger.info("Reddit total: %d posts", len(all_posts))
    return all_posts
