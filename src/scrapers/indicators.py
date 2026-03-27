"""Macro economic indicators scraper.

Fetches:
  • DXY (US Dollar Index)
  • US 10Y Treasury Yield
  • MOVE Index (bond volatility)
  • FedWatch target rate probabilities (next 3 FOMC meetings)

DXY, US10Y, MOVE: fetched from yfinance
FedWatch: scraped from CME website
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "MacroSentimentBot/1.0"}
_FEDWATCH_RATE_COL_RE = re.compile(r"\d")
_FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
_FEDWATCH_META_COLS = {
    "date",
    "meeting",
    "meeting_date",
    "meeting_month",
    "meeting_year",
    "watch_date",
    "implied_rate",
    "expected_change",
    "hike_prob",
    "cut_prob",
    "no_change_prob",
}
_FFF_SUFFIXES = (".CBT", "=F")


def _download_close(symbol: str, period: str = "5d") -> Optional[float]:
    """Fetch latest close from yfinance for a symbol."""
    df = yf.download(
        symbol,
        period=period,
        auto_adjust=False,
        progress=False,
        timeout=12,
    )
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    if "Close" not in df.columns:
        return None
    closes = df["Close"].dropna()
    if closes.empty:
        return None
    return float(closes.iloc[-1])


def _fetch_fred_latest(series_id: str) -> Optional[float]:
    """Fetch latest non-missing value from FRED CSV endpoint."""
    try:
        resp = requests.get(
            _FRED_CSV.format(series_id=series_id),
            headers=_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        if len(lines) < 2:
            return None

        col = series_id
        for line in reversed(lines[1:]):
            parts = line.split(",")
            if len(parts) < 2:
                continue
            val = parts[1].strip()
            if not val or val == ".":
                continue
            return float(val)
    except Exception as exc:
        logger.debug("Error fetching FRED %s: %s", series_id, exc)
    return None


def _get_watch_date_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _fff_history_from_yfinance(symbol: str) -> pd.DataFrame:
    """Fetch a Fed Funds futures contract history in pyfedwatch-compatible format."""
    last_error: Exception | None = None
    for suffix in _FFF_SUFFIXES:
        ticker = f"{symbol}{suffix}"
        try:
            df = yf.download(
                ticker,
                period="24mo",
                auto_adjust=False,
                progress=False,
                timeout=12,
            )
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            if "Close" not in df.columns:
                continue
            out = df.reset_index()[["Date", "Close"]].copy()
            out["Date"] = pd.to_datetime(out["Date"]).dt.strftime("%Y-%m-%d")
            return out
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise ValueError(f"No yfinance data for {symbol}: {last_error}")
    raise ValueError(f"No yfinance data for {symbol}")


def _extract_fedwatch_rows(df: pd.DataFrame, max_rows: int = 3) -> list[dict]:
    """Normalize pyfedwatch output into compact meeting/probability rows."""
    if df.empty:
        return []

    rows: list[dict] = []
    for _, row in df.tail(max_rows).iterrows():
        meeting = None
        for key in ("meeting_date", "meeting", "date", "Meeting"):
            value = row.get(key)
            if value is not None and str(value).strip():
                meeting = str(value)
                break

        probs: dict[str, float] = {}
        for col, value in row.items():
            col_s = str(col).strip()
            if col_s.lower() in _FEDWATCH_META_COLS:
                continue
            if not _FEDWATCH_RATE_COL_RE.search(col_s):
                continue
            if not isinstance(value, (int, float)):
                continue
            val = float(value)
            if val < 0 or val > 100:
                continue
            probs[col_s] = round(val, 2)

        if probs:
            rows.append({"meeting": meeting, "probabilities": probs})
    return rows


def _fetch_dxy() -> Optional[dict]:
    """Fetch current DXY (US Dollar Index) from yfinance."""
    for symbol in ("DX-Y.NYB", "^DXY", "DX=F"):
        try:
            hist = yf.download(
                symbol,
                period="5d",
                auto_adjust=False,
                progress=False,
                timeout=12,
            )
            if hist.empty:
                continue
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = [c[0] for c in hist.columns]
            if "Close" not in hist.columns:
                continue
            closes = hist["Close"].dropna()
            if closes.empty:
                continue

            current = float(closes.iloc[-1])
            return {
                "label": "US Dollar Index",
                "ticker": symbol,
                "value": round(current, 2),
                "value_unit": "index",
            }
        except Exception as exc:
            logger.debug("Error fetching DXY via %s: %s", symbol, exc)
            continue

    logger.warning("DXY: empty data across all ticker fallbacks")
    return None


def _fetch_us10y() -> Optional[dict]:
    """Fetch current US 10Y Treasury Yield using FRED then yfinance fallback."""
    fred_val = _fetch_fred_latest("DGS10")
    if isinstance(fred_val, (int, float)):
        return {
            "label": "US 10Y Treasury Yield",
            "ticker": "DGS10",
            "value": round(float(fred_val), 3),
            "value_unit": "yield_pct",
        }

    for symbol in ("^TNX", "TNX"):
        try:
            current = _download_close(symbol, period="5d")
            if current is None:
                continue
            # Yahoo's ^TNX is quoted as yield*10, e.g., 43.2 => 4.32%
            if symbol.upper().endswith("TNX") and current > 15:
                current = current / 10.0
            return {
                "label": "US 10Y Treasury Yield",
                "ticker": symbol,
                "value": round(current, 3),
                "value_unit": "yield_pct",
            }
        except Exception as exc:
            logger.debug("Error fetching US10Y via %s: %s", symbol, exc)

    logger.warning("US10Y: empty data across FRED/yfinance fallbacks")
    return None


def _fetch_move_index() -> Optional[dict]:
    """Fetch current MOVE Index (bond volatility) from yfinance."""
    for symbol in ("^MOVE", "MOVE"):
        try:
            current = _download_close(symbol, period="5d")
            if current is None:
                continue
            return {
                "label": "MOVE Index (Bond Vol)",
                "ticker": symbol,
                "value": round(current, 2),
                "value_unit": "index",
            }
        except Exception as exc:
            logger.debug("Error fetching MOVE via %s: %s", symbol, exc)
            continue

    logger.warning("MOVE: empty data across all ticker fallbacks")
    return None


def _fetch_fedwatch_rates() -> Optional[dict]:
    """Fetch FedWatch probabilities using pyfedwatch with robust fallbacks."""
    try:
        import pyfedwatch as fw
    except Exception as exc:
        logger.debug("FedWatch unavailable (pyfedwatch import failed): %s", exc)
        return None

    watch_date = _get_watch_date_utc()
    try:
        fomc_df = None
        for getter_name in ("get_fomc_data", "get_fomc_data_fed"):
            getter = getattr(fw.datareader, getter_name, None)
            if getter is None:
                continue
            try:
                candidate = getter()
                if candidate is not None and not candidate.empty:
                    fomc_df = candidate
                    break
            except Exception:
                continue

        if fomc_df is None or fomc_df.empty:
            logger.warning("FedWatch: could not load FOMC calendar")
            return None

        today = datetime.now(timezone.utc).date()
        fomc_dates = pd.to_datetime(fomc_df.index, errors="coerce")
        future_dates = [d.to_pydatetime() for d in fomc_dates if not pd.isna(d) and d.date() >= today]
        if not future_dates:
            logger.warning("FedWatch: no future FOMC dates found")
            return None

        num_upcoming = min(3, len(future_dates))
        calc = fw.fedwatch.FedWatch(
            watch_date=watch_date,
            num_upcoming=num_upcoming,
            fomc_dates=future_dates,
            user_func=_fff_history_from_yfinance,
        )

        table = calc.generate_hike_info(rate_cols=True)
        meetings = _extract_fedwatch_rows(table, max_rows=num_upcoming)
        if not meetings:
            logger.warning("FedWatch: empty probabilities table")
            return None

        return {
            "label": "FedWatch Target Rate Probabilities",
            "source": "pyfedwatch",
            "watch_date": watch_date,
            "meetings": meetings,
            "value_unit": "probability_pct",
        }
    except Exception as exc:
        logger.warning("FedWatch fetch failed: %s", exc)
        return None


def fetch_indicators() -> dict:
    """Fetch all macro indicators.
    
    Returns dict:
    {
        "dxy": {...},
        "us10y": {...},
        "move": {...},
        "fedwatch": {...} or None
    }
    """
    logger.info("Fetching macro indicators…")
    
    dxy = _fetch_dxy()
    us10y = _fetch_us10y()
    move = _fetch_move_index()
    fedwatch = _fetch_fedwatch_rates()
    
    return {
        "dxy": dxy,
        "us10y": us10y,
        "move": move,
        "fedwatch": fedwatch,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
