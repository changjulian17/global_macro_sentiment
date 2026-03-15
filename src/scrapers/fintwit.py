"""FinTwit scraper — uses public Nitter RSS instances (no API key required).

Nitter is a privacy-friendly Twitter front-end that exposes RSS feeds at:
  https://<instance>/<username>/rss

Multiple public instances are tried in order; the last working instance is
reused for subsequent accounts to reduce latency.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests

logger = logging.getLogger(__name__)

# Public Nitter instances — add/remove as availability changes.
# Up-to-date list: https://github.com/zedeus/nitter/wiki/Instances
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
    "https://nitter.unixfox.eu",
    "https://nitter.cz",
    "https://bird.trom.tf",
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MacroSentimentBot/1.0)"}
_HTML_RE = re.compile(r"<[^>]+>")


def _clean(html: str) -> str:
    return " ".join(_HTML_RE.sub(" ", html).split()).strip()


def _entry_text(entry: dict) -> str:
    """Extract robust text from RSS entry with fallbacks for sparse items."""
    candidates = [
        entry.get("summary", ""),
        entry.get("description", ""),
        entry.get("title", ""),
    ]

    for raw in candidates:
        txt = _clean(raw or "")
        if txt:
            # Some feeds prefix title text as "username: tweet".
            if ": " in txt and len(txt.split(": ", 1)[0]) < 40:
                txt = txt.split(": ", 1)[1].strip()
            if txt:
                return txt

    link = (entry.get("link", "") or "").strip()
    return "Tweet (text unavailable)" if link else ""


def _try_instance(instance: str, username: str, timeout: int = 10) -> Optional[list]:
    """Attempt to fetch RSS from one Nitter instance. Returns posts or None."""
    url = f"{instance}/{username}/rss"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        feed = feedparser.parse(resp.content)
        if not feed.entries:
            return None
        posts = []
        for entry in feed.entries[:25]:
            text = _entry_text(entry)
            t = entry.get("published_parsed")
            dt = datetime(*t[:6], tzinfo=timezone.utc) if t else datetime.now(timezone.utc)
            posts.append(
                {
                    "username": username,
                    "source": username,
                    "text": text,
                    "url": entry.get("link", ""),
                    "published": dt.isoformat(),
                }
            )
        return posts
    except Exception as exc:
        logger.debug("Nitter %s / @%s failed: %s", instance, username, exc)
        return None


def fetch_account(
    username: str, working_instance: Optional[str] = None
) -> tuple[list, Optional[str]]:
    """Fetch tweets for one account.

    Returns (posts, working_instance).  Tries the last-known working instance
    first so most calls only need one HTTP request.
    """
    instances = list(NITTER_INSTANCES)
    if working_instance and working_instance in instances:
        instances.remove(working_instance)
        instances.insert(0, working_instance)

    for instance in instances:
        result = _try_instance(instance, username)
        if result is not None:
            return result, instance
        time.sleep(0.3)

    logger.warning("All Nitter instances failed for @%s", username)
    return [], None


def fetch_all(accounts: list) -> list:
    """Fetch tweets for all active accounts in *accounts* list."""
    all_posts: list = []
    working_instance: Optional[str] = None
    active = [a for a in accounts if a.get("active", True)]

    logger.info("Fetching FinTwit for %d active accounts…", len(active))
    for account in active:
        username = account["username"]
        posts, working_instance = fetch_account(username, working_instance)
        logger.info("  @%s: %d tweets", username, len(posts))
        all_posts.extend(posts)
        time.sleep(1.2)  # be respectful — ~1 req/sec

    logger.info("FinTwit total: %d tweets", len(all_posts))
    return all_posts
