"""Global liquidity indicator using free public FRED CSV endpoints.

Definition (weekly):
  composite_z = z(13w % change in Fed assets)
              + z(13w % change in ECB assets)
              + z(13w % change in BoJ assets)
              - z(13w % change in broad USD index)

Score scaling:
  liquidity_score = clip(50 + 10 * composite_z, 0, 100)

All data is fetched from free CSV endpoints (no API key required).
"""

from __future__ import annotations

import csv
import logging
import math
from bisect import bisect_right
from datetime import datetime
from io import StringIO

import requests

logger = logging.getLogger(__name__)

_FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
_HEADERS = {"User-Agent": "MacroSentimentBot/1.0"}

# Weekly-ish central bank balance sheet proxies + broad dollar index
_SERIES = {
    "fed_assets": "WALCL",
    "ecb_assets": "ECBASSETSW",
    "boj_assets": "JPNASSETS",
    "usd_index": "DTWEXBGS",
}


def _parse_date(value: str) -> datetime.date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _fetch_fred_series(series_id: str) -> list[tuple[datetime.date, float]]:
    url = _FRED_CSV.format(series_id=series_id)
    resp = requests.get(url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()

    reader = csv.DictReader(StringIO(resp.text))
    out: list[tuple[datetime.date, float]] = []
    for row in reader:
        ds = row.get("observation_date", "")
        vs = row.get(series_id, "")
        if not ds or not vs or vs == ".":
            continue
        try:
            out.append((_parse_date(ds), float(vs)))
        except ValueError:
            continue

    out.sort(key=lambda x: x[0])
    if len(out) < 40:
        raise ValueError(f"Series {series_id} returned too few points: {len(out)}")
    return out


def _asof_values(reference_dates: list[datetime.date], series: list[tuple[datetime.date, float]]) -> list[float | None]:
    dates = [d for d, _ in series]
    vals = [v for _, v in series]
    out: list[float | None] = []
    for d in reference_dates:
        idx = bisect_right(dates, d) - 1
        out.append(vals[idx] if idx >= 0 else None)
    return out


def _pct_change(values: list[float | None], periods: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(periods, len(values)):
        cur = values[i]
        prev = values[i - periods]
        if cur is None or prev is None or prev == 0:
            continue
        out[i] = (cur / prev - 1.0) * 100.0
    return out


def _zscore(values: list[float | None]) -> list[float | None]:
    finite = [v for v in values if isinstance(v, float) and math.isfinite(v)]
    if len(finite) < 8:
        return [None] * len(values)
    mean = sum(finite) / len(finite)
    var = sum((v - mean) ** 2 for v in finite) / len(finite)
    std = math.sqrt(var)
    if std == 0:
        return [None] * len(values)

    out: list[float | None] = []
    for v in values:
        if v is None or not math.isfinite(v):
            out.append(None)
        else:
            out.append((v - mean) / std)
    return out


def _label(score: float) -> str:
    if score >= 65:
        return "Very Loose"
    if score >= 55:
        return "Loose"
    if score >= 45:
        return "Neutral"
    if score >= 35:
        return "Tight"
    return "Very Tight"


def fetch_global_liquidity(lookback_points: int = 52) -> dict:
    """Return current global liquidity score and a weekly history series."""
    try:
        fed = _fetch_fred_series(_SERIES["fed_assets"])
        ecb = _fetch_fred_series(_SERIES["ecb_assets"])
        boj = _fetch_fred_series(_SERIES["boj_assets"])
        usd = _fetch_fred_series(_SERIES["usd_index"])
    except Exception as exc:
        logger.warning("Global liquidity fetch failed: %s", exc)
        return {
            "score": None,
            "label": "Unavailable",
            "composite_z": None,
            "history": {"dates": [], "scores": []},
        }

    ref_dates = [d for d, _ in fed]
    fed_vals = [v for _, v in fed]
    ecb_vals = _asof_values(ref_dates, ecb)
    boj_vals = _asof_values(ref_dates, boj)
    usd_vals = _asof_values(ref_dates, usd)

    periods = 13
    fed_chg = _pct_change(fed_vals, periods)
    ecb_chg = _pct_change(ecb_vals, periods)
    boj_chg = _pct_change(boj_vals, periods)
    usd_chg = _pct_change(usd_vals, periods)

    fed_z = _zscore(fed_chg)
    ecb_z = _zscore(ecb_chg)
    boj_z = _zscore(boj_chg)
    usd_z = _zscore(usd_chg)

    composite: list[float | None] = [None] * len(ref_dates)
    scores: list[float | None] = [None] * len(ref_dates)

    for i in range(len(ref_dates)):
        vals = (fed_z[i], ecb_z[i], boj_z[i], usd_z[i])
        if any(v is None for v in vals):
            continue
        comp = float(fed_z[i] + ecb_z[i] + boj_z[i] - usd_z[i])
        composite[i] = comp
        scores[i] = max(0.0, min(100.0, 50.0 + 10.0 * comp))

    valid_idx = [i for i, s in enumerate(scores) if s is not None]
    if not valid_idx:
        return {
            "score": None,
            "label": "Unavailable",
            "composite_z": None,
            "history": {"dates": [], "scores": []},
        }

    last_i = valid_idx[-1]
    start_i = valid_idx[max(0, len(valid_idx) - lookback_points)]
    hist_slice = range(start_i, last_i + 1)

    hist_dates = [ref_dates[i].isoformat() for i in hist_slice if scores[i] is not None]
    hist_scores = [round(float(scores[i]), 2) for i in hist_slice if scores[i] is not None]

    return {
        "score": round(float(scores[last_i]), 2),
        "label": _label(float(scores[last_i])),
        "composite_z": round(float(composite[last_i]), 4) if composite[last_i] is not None else None,
        "components_13w_pct": {
            "fed_assets": round(float(fed_chg[last_i]), 3) if fed_chg[last_i] is not None else None,
            "ecb_assets": round(float(ecb_chg[last_i]), 3) if ecb_chg[last_i] is not None else None,
            "boj_assets": round(float(boj_chg[last_i]), 3) if boj_chg[last_i] is not None else None,
            "usd_index": round(float(usd_chg[last_i]), 3) if usd_chg[last_i] is not None else None,
        },
        "history": {
            "dates": hist_dates,
            "scores": hist_scores,
        },
    }
