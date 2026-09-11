"""Sentiment analysis module.

Default engine: VADER (vaderSentiment) augmented with a financial lexicon.
Optional engine: FinBERT (ProsusAI/finbert via transformers) — pass
  use_finbert=True.  First run downloads ~420 MB; subsequent runs use cache.

Score range: -1.0 (very bearish) → 0.0 (neutral) → +1.0 (very bullish).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Recency weighting — newer items count more than older ones.
# ---------------------------------------------------------------------------
# Weight halves every RECENCY_HALF_LIFE_DAYS days of age (exponential decay).
RECENCY_HALF_LIFE_DAYS = 7.0
_DECAY_LAMBDA = math.log(2) / RECENCY_HALF_LIFE_DAYS


def _recency_weight(published: str, now: Optional[datetime] = None) -> float:
    """Exponential-decay weight for an item based on its `published` timestamp.

    weight = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)

    Items with a missing/unparseable timestamp get full weight (1.0) rather
    than being dropped, so older data without dates isn't silently zeroed.
    """
    if not published:
        return 1.0
    try:
        ts = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return 1.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    age_days = max(0.0, (now - ts).total_seconds() / 86400)
    return math.exp(-_DECAY_LAMBDA * age_days)

# ---------------------------------------------------------------------------
# Financial sentiment word lists that augment VADER's general-purpose lexicon
# ---------------------------------------------------------------------------
_BULLISH: dict[str, float] = {
    "rally": 2.0, "rallied": 1.8, "breakout": 1.8, "bullish": 2.2,
    "upside": 1.5, "buy": 1.0, "buying": 1.0, "long": 0.6,
    "growth": 1.0, "surge": 1.8, "surged": 1.8, "soar": 1.8, "soared": 1.8,
    "recovery": 1.5, "rebound": 1.5, "strong": 1.0, "outperform": 1.5,
    "upgrade": 1.5, "beat": 1.2, "exceed": 1.2, "record": 0.8,
    "accumulate": 1.0, "overweight": 1.0, "momentum": 0.8,
    "oversold": 1.2, "undervalued": 1.2, "stimulus": 0.8,
    "easing": 0.8, "cut": 0.5, "dovish": 1.0,
}

_BEARISH: dict[str, float] = {
    "crash": -2.8, "crashed": -2.8, "collapse": -2.5, "collapsed": -2.5,
    "bearish": -2.2, "downside": -1.5, "sell": -1.0, "selling": -1.0,
    "short": -0.6, "recession": -2.2, "stagflation": -2.5,
    "decline": -1.2, "declined": -1.2, "plunge": -2.2, "plunged": -2.2,
    "slump": -1.5, "slumped": -1.5, "weak": -1.0, "weakness": -1.2,
    "underperform": -1.5, "downgrade": -1.5,
    "miss": -1.0, "missed": -1.2, "disappoint": -1.5, "disappointing": -1.5,
    "default": -2.5, "contagion": -2.2, "risk": -0.5,
    "concern": -0.8, "concerns": -0.8, "worry": -1.0, "worried": -1.0,
    "fear": -1.5, "fears": -1.5, "overbought": -1.2, "overvalued": -1.2,
    "inflation": -0.6, "hawkish": -0.8, "tightening": -0.8,
    "contraction": -1.5, "slowdown": -1.2,
}

# ---------------------------------------------------------------------------
# Lazy-loaded engine singletons
# ---------------------------------------------------------------------------
_vader = None
_finbert = None


def _get_vader():
    global _vader
    if _vader is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore
        _vader = SentimentIntensityAnalyzer()
        _vader.lexicon.update(_BULLISH)
        _vader.lexicon.update(_BEARISH)
    return _vader


def _get_finbert():
    global _finbert
    if _finbert is None:
        try:
            from transformers import pipeline  # type: ignore
            logger.info("Loading FinBERT model…  (first run downloads ~420 MB)")
            _finbert = pipeline(
                "text-classification",
                model="ProsusAI/finbert",
                device=-1,  # CPU only
                truncation=True,
            )
            logger.info("FinBERT ready.")
        except Exception as exc:
            logger.warning("FinBERT unavailable (%s) — falling back to VADER.", exc)
            _finbert = None
    return _finbert


# ---------------------------------------------------------------------------
# Core analysis helpers
# ---------------------------------------------------------------------------

def _score_vader(text: str) -> float:
    return _get_vader().polarity_scores(text)["compound"]


def _score_finbert(text: str) -> float:
    pipe = _get_finbert()
    if pipe is None:
        return _score_vader(text)
    try:
        result = pipe(text[:512])[0]
        label, conf = result["label"], result["score"]
        if label == "positive":
            return conf
        elif label == "negative":
            return -conf
        return 0.0
    except Exception:
        return _score_vader(text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(text: str, use_finbert: bool = False) -> dict:
    """Return sentiment dict with keys: score, label, confidence."""
    if not text or not text.strip():
        return {"score": 0.0, "label": "neutral", "confidence": 0.0}

    raw = _score_finbert(text) if use_finbert else _score_vader(text)
    score = max(-1.0, min(1.0, raw))

    if score >= 0.3:
        label = "bullish"
    elif score <= -0.3:
        label = "bearish"
    else:
        label = "neutral"

    return {
        "score":      round(score, 4),
        "label":      label,
        "confidence": round(abs(score), 4),
    }


def analyze_batch(items: list, use_finbert: bool = False) -> list:
    """Add score/label/confidence fields to every item in *items*."""
    out = []
    for item in items:
        sentiment = analyze(item.get("text", ""), use_finbert=use_finbert)
        out.append({**item, **sentiment})
    return out


def aggregate_sentiment(items: list) -> dict:
    """Compute summary statistics from a list of scored items.

    Each item is weighted by recency (exponential decay, see
    `_recency_weight`) so fresher news moves the mean and bull/bear split
    more than stale news, instead of every item counting equally.
    """
    if not items:
        return {
            "mean": 0.0,
            "bullish_pct": 0.0,
            "neutral_pct": 0.0,
            "bearish_pct": 0.0,
            "count": 0,
        }
    now = datetime.now(timezone.utc)
    weights = [_recency_weight(i.get("published", ""), now) for i in items]
    scores = [i.get("score", 0.0) for i in items]
    labels = [i.get("label", "neutral") for i in items]
    n = len(items)
    total_weight = sum(weights) or 1.0

    def _weighted_pct(label: str) -> float:
        w = sum(wt for wt, lbl in zip(weights, labels) if lbl == label)
        return round(w / total_weight * 100, 1)

    weighted_mean = sum(s * w for s, w in zip(scores, weights)) / total_weight

    return {
        "mean":        round(weighted_mean, 4),
        "bullish_pct": _weighted_pct("bullish"),
        "neutral_pct": _weighted_pct("neutral"),
        "bearish_pct": _weighted_pct("bearish"),
        "count":       n,
    }
