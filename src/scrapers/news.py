"""News scraper — pulls headlines from free public RSS feeds.

No API keys required.  Covers macro/markets/economics beats across
Reuters, CNBC, MarketWatch, WSJ, Bloomberg, FT, Yahoo Finance, etc.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests

logger = logging.getLogger(__name__)

NEWS_FEEDS = [
    {"name": "Reuters Business",   "url": "https://feeds.reuters.com/reuters/businessNews"},
    {"name": "Reuters Markets",    "url": "https://feeds.reuters.com/reuters/financialmarkets"},
    {"name": "CNBC Markets",       "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html"},
    {"name": "CNBC Finance",       "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html"},
    {"name": "CNBC Economy",       "url": "https://www.cnbc.com/id/20910274/device/rss/rss.html"},
    {"name": "MarketWatch Top",    "url": "https://feeds.marketwatch.com/marketwatch/topstories/"},
    {"name": "MarketWatch Markets","url": "https://feeds.marketwatch.com/marketwatch/marketpulse/"},
    {"name": "WSJ Markets",        "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
    {"name": "Yahoo Finance",      "url": "https://finance.yahoo.com/news/rssindex"},
    {"name": "Bloomberg Markets",  "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"name": "FT Markets",         "url": "https://www.ft.com/rss/home/uk"},
    {"name": "Seeking Alpha",      "url": "https://seekingalpha.com/market_currents.xml"},
    {"name": "Investopedia",       "url": "https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_headline"},
    {"name": "The Economist",      "url": "https://www.economist.com/finance-and-economics/rss.xml"},
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
    )
}
_HTML_RE = re.compile(r"<[^>]+>")


def _clean(raw: str) -> str:
    text = _HTML_RE.sub(" ", raw)
    return re.sub(r"\s+", " ", text).strip()[:1000]


def _parse_date(entry: dict) -> str:
    for field in ("published_parsed", "updated_parsed"):
        t = entry.get(field)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def fetch_feed(feed_config: dict, limit: int = 20) -> list:
    try:
        resp = requests.get(feed_config["url"], headers=_HEADERS, timeout=12)
        if resp.status_code not in (200,):
            logger.debug("News '%s': HTTP %d", feed_config["name"], resp.status_code)
            return []
        parsed = feedparser.parse(resp.content)
        articles = []
        for entry in parsed.entries[:limit]:
            title = _clean(entry.get("title", ""))
            summary = _clean(entry.get("summary", entry.get("description", "")))
            text = f"{title}. {summary}" if summary else title
            articles.append(
                {
                    "source": feed_config["name"],
                    "title": title,
                    "text": text,
                    "url": entry.get("link", ""),
                    "published": _parse_date(entry),
                }
            )
        return articles
    except Exception as exc:
        logger.debug("News '%s' error: %s", feed_config["name"], exc)
        return []


def fetch_all() -> list:
    all_articles: list = []
    for feed in NEWS_FEEDS:
        articles = fetch_feed(feed)
        logger.info("  %s: %d articles", feed["name"], len(articles))
        all_articles.extend(articles)
    logger.info("News total: %d articles", len(all_articles))
    return all_articles
