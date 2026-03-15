"""Market data scraper — uses yfinance (free, no API key required).

Also fetches:
  • Crypto Fear & Greed from alternative.me  (free, no key)
  • Equity Fear & Greed from CNN's public data endpoint (best-effort)

Tickers are fetched concurrently via ThreadPoolExecutor to keep run times short.
"""

from __future__ import annotations

import logging
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import StringIO
from typing import Optional

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

_FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# Key global macro assets grouped by category
ASSETS: dict[str, dict] = {
    # US Equities
    "SPY":      {"name": "S&P 500 ETF",        "category": "equities"},
    "QQQ":      {"name": "Nasdaq 100 ETF",      "category": "equities"},
    "IWM":      {"name": "Russell 2000 ETF",    "category": "equities"},
    "DIA":      {"name": "Dow Jones ETF",        "category": "equities"},
    # Volatility
    "^VIX":     {"name": "VIX",                  "category": "volatility"},
    "^MOVE":    {"name": "MOVE Index",           "category": "volatility"},
    # International
    "EEM":      {"name": "Emerging Markets ETF", "category": "international"},
    "EFA":      {"name": "Developed Markets ETF","category": "international"},
    "FXI":      {"name": "China Large Cap ETF",  "category": "international"},
    "EWJ":      {"name": "Japan ETF",            "category": "international"},
    "EWZ":      {"name": "Brazil ETF",           "category": "international"},
    # FX
    "DX-Y.NYB": {"name": "US Dollar Index",      "category": "fx"},
    "EURUSD=X": {"name": "EUR/USD",              "category": "fx"},
    "USDJPY=X": {"name": "USD/JPY",              "category": "fx"},
    "GBPUSD=X": {"name": "GBP/USD",              "category": "fx"},
    "USDCNY=X": {"name": "USD/CNY",              "category": "fx"},
    # Commodities
    "GLD":      {"name": "Gold ETF",             "category": "commodities"},
    "SLV":      {"name": "Silver ETF",           "category": "commodities"},
    "CL=F":     {"name": "Crude Oil WTI",        "category": "commodities"},
    "NG=F":     {"name": "Natural Gas",          "category": "commodities"},
    "CORN":     {"name": "Corn ETF",             "category": "commodities"},
    # Crypto
    "BTC-USD":  {"name": "Bitcoin",              "category": "crypto"},
    "ETH-USD":  {"name": "Ethereum",             "category": "crypto"},
}

YIELD_SERIES: dict[str, dict] = {
    "DGS2":  {"name": "US 2Y Treasury Yield",  "category": "rates"},
    "DGS10": {"name": "US 10Y Treasury Yield", "category": "rates"},
    "DGS30": {"name": "US 30Y Treasury Yield", "category": "rates"},
}

CREDIT_SPREAD_SERIES: dict[str, dict] = {
    "BAMLH0A0HYM2": {"name": "US High Yield OAS",       "category": "credit"},
    "BAMLC0A0CM":   {"name": "US Investment Grade OAS", "category": "credit"},
}

_HEADERS = {"User-Agent": "MacroSentimentBot/1.0"}


def _fetch_ticker(ticker: str) -> Optional[dict]:
    try:
        hist = yf.Ticker(ticker).history(period="1mo", auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return None
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return None
        cur = float(closes.iloc[-1])
        p1d  = float(closes.iloc[-2])
        p5d  = float(closes.iloc[-6])  if len(closes) >= 6  else float(closes.iloc[0])
        p1mo = float(closes.iloc[0])
        return {
            **ASSETS[ticker],
            "ticker":     ticker,
            "price":      round(cur, 4),
            "change_1d":  round((cur - p1d)  / p1d  * 100, 3),
            "change_5d":  round((cur - p5d)  / p5d  * 100, 3),
            "change_1mo": round((cur - p1mo) / p1mo * 100, 3),
        }
    except Exception as exc:
        logger.debug("Error fetching %s: %s", ticker, exc)
        return None


def _fetch_fred_series(series_id: str) -> list[tuple[str, float]]:
    resp = requests.get(
        _FRED_CSV.format(series_id=series_id),
        headers=_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    reader = csv.DictReader(StringIO(resp.text))
    out: list[tuple[str, float]] = []
    for row in reader:
        ds = row.get("observation_date", "")
        vs = row.get(series_id, "")
        if not ds or not vs or vs == ".":
            continue
        try:
            out.append((ds, float(vs)))
        except ValueError:
            continue
    if len(out) < 2:
        raise ValueError(f"FRED {series_id}: insufficient data")
    return out


def _fred_level_delta_row(series_id: str, meta: dict, level_unit: str) -> Optional[dict]:
    try:
        series = _fetch_fred_series(series_id)
        vals = [v for _, v in series]
        cur = vals[-1]
        p1d = vals[-2]
        p5d = vals[-6] if len(vals) >= 6 else vals[0]
        p1mo = vals[-22] if len(vals) >= 22 else vals[0]
        return {
            **meta,
            "ticker": series_id,
            "price": round(cur, 4),
            "change_1d": round((cur - p1d) * 100, 2),
            "change_5d": round((cur - p5d) * 100, 2),
            "change_1mo": round((cur - p1mo) * 100, 2),
            "value_unit": level_unit,
            "delta_unit": "bps",
        }
    except Exception as exc:
        logger.debug("Error fetching FRED %s: %s", series_id, exc)
        return None


def fetch_market_data() -> dict:
    results: dict = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_ticker, t): t for t in ASSETS}
        for fut in as_completed(futures):
            ticker = futures[fut]
            data = fut.result()
            if data:
                results[ticker] = data

    # Treasury yields (replace bond ETFs with direct yield levels)
    for series_id, meta in YIELD_SERIES.items():
        row = _fred_level_delta_row(series_id, meta, level_unit="yield_pct")
        if row:
            results[series_id] = row

    # Credit spreads in basis points (HY + IG)
    for series_id, meta in CREDIT_SPREAD_SERIES.items():
        row = _fred_level_delta_row(series_id, meta, level_unit="spread_bps")
        if row:
            results[series_id] = row

    total_targets = len(ASSETS) + len(YIELD_SERIES) + len(CREDIT_SPREAD_SERIES)
    logger.info("Market data: %d / %d assets fetched", len(results), total_targets)
    return results


def fetch_fear_greed() -> dict:
    result: dict = {}

    # --- Crypto Fear & Greed (alternative.me) — reliable free endpoint ---
    try:
        resp = requests.get(
            "https://api.alternative.me/fng/?limit=7",
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            values = resp.json().get("data", [])
            if values:
                latest = values[0]
                result["crypto_fg"] = {
                    "value": int(latest["value"]),
                    "label": latest["value_classification"],
                    "history": [int(v["value"]) for v in values],
                }
    except Exception as exc:
        logger.warning("Crypto F&G error: %s", exc)

    # --- CNN Equity Fear & Greed (best-effort; may be blocked) ---
    try:
        resp = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={**_HEADERS, "Referer": "https://edition.cnn.com/"},
            timeout=10,
        )
        if resp.status_code == 200:
            fg = resp.json().get("fear_and_greed", {})
            score  = fg.get("score")
            rating = fg.get("rating", "")
            if score is not None:
                result["equity_fg"] = {
                    "value": round(float(score)),
                    "label": rating.replace("_", " ").title(),
                }
    except Exception as exc:
        logger.debug("CNN F&G error (may be blocked): %s", exc)

    return result
