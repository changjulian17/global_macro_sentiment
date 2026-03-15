#!/usr/bin/env python3
"""Global Macro Sentiment — main batch runner.

Run from the project root:
  python run.py                    # standard run, opens browser
  python run.py --sync-accounts    # merge curated account list first, then run
  python run.py --use-finbert      # use FinBERT instead of VADER (better accuracy)
  python run.py --no-browser       # generate report without opening it
  python run.py --skip-fintwit     # skip FinTwit scraping (useful when Nitter is down)

The report is always saved to reports/latest.html.
Each run is stored in data/sentiment.db for historical charting.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT           = Path(__file__).parent
ACCOUNTS_FILE  = ROOT / "config" / "accounts.json"

# ---------------------------------------------------------------------------
# Built-in curated account list
# Merged with user's accounts.json on --sync-accounts.
# New accounts are ADDED; nothing is ever removed automatically.
# ---------------------------------------------------------------------------
CURATED_ACCOUNTS: list[dict] = [
    {"username": "RayDalio",        "name": "Ray Dalio",           "category": "macro"},
    {"username": "elerianm",        "name": "Mohamed El-Erian",    "category": "macro"},
    {"username": "BillAckman",      "name": "Bill Ackman",         "category": "hedge_fund"},
    {"username": "GundlachCapital", "name": "Jeffrey Gundlach",    "category": "fixed_income"},
    {"username": "MacroAlf",        "name": "Alfonso Peccatiello", "category": "macro"},
    {"username": "LukeGromen",      "name": "Luke Gromen",         "category": "macro"},
    {"username": "RaoulGMI",        "name": "Raoul Pal",           "category": "macro"},
    {"username": "TaviCosta",       "name": "Tavi Costa",          "category": "macro"},
    {"username": "mark_dow",        "name": "Mark Dow",            "category": "macro"},
    {"username": "fleckenst",       "name": "Stan Fleckenstein",   "category": "macro"},
    {"username": "JeffSnider_AIP",  "name": "Jeff Snider",         "category": "macro"},
    {"username": "michaellebowitz", "name": "Michael Lebowitz",    "category": "macro"},
    {"username": "LizAnnSonders",   "name": "Liz Ann Sonders",     "category": "macro"},
    {"username": "hmeisler",        "name": "Helene Meisler",      "category": "technicals"},
    {"username": "zerohedge",       "name": "ZeroHedge",           "category": "news"},
    {"username": "NorthmanTrader",  "name": "Sven Henrich",        "category": "macro"},
    {"username": "hussmanjp",       "name": "John Hussman",        "category": "macro"},
    {"username": "jessefelder",     "name": "Jesse Felder",        "category": "macro"},
    {"username": "LynAldenContact", "name": "Lyn Alden",           "category": "macro"},
    {"username": "saxena_puru",     "name": "Puru Saxena",         "category": "macro"},
    {"username": "gametheoryMM",    "name": "Game Theory MM",      "category": "macro"},
    {"username": "PeterSchiff",     "name": "Peter Schiff",        "category": "macro"},
    {"username": "StanChart_FX",    "name": "Steven Englander",    "category": "fx"},
    {"username": "DavidSchawel",    "name": "David Schawel",       "category": "fixed_income"},
    {"username": "ReformedBroker",  "name": "Josh Brown",          "category": "equities"},
    {"username": "NDR_Research",    "name": "Ned Davis Research",  "category": "macro"},
    {"username": "johnauthers",     "name": "John Authers",        "category": "macro"},
    {"username": "biancoresearch",  "name": "Jim Bianco",          "category": "macro"},
    {"username": "kevinmuir",       "name": "Kevin Muir",          "category": "macro"},
    {"username": "hkuppy",          "name": "Harris Kupperman",    "category": "macro"},
    {"username": "ErikVoorhees",    "name": "Erik Voorhees",       "category": "crypto"},
    {"username": "APompliano",      "name": "Anthony Pompliano",   "category": "crypto"},
]


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

def _load_accounts() -> list:
    if not ACCOUNTS_FILE.exists():
        logger.warning(
            "accounts.json not found — using built-in curated list. "
            "Run with --sync-accounts to create the file."
        )
        return [{**a, "active": True} for a in CURATED_ACCOUNTS]
    with ACCOUNTS_FILE.open() as fh:
        return json.load(fh).get("accounts", [])


def _sync_accounts(accounts: list) -> list:
    """Merge CURATED_ACCOUNTS into *accounts* (add only, never remove)."""
    existing = {a["username"].lower() for a in accounts}
    added = 0
    for acct in CURATED_ACCOUNTS:
        if acct["username"].lower() not in existing:
            accounts.append({**acct, "active": True})
            existing.add(acct["username"].lower())
            added += 1
    logger.info("Account sync: +%d new accounts (total %d)", added, len(accounts))
    return accounts


def _save_accounts(accounts: list) -> None:
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ACCOUNTS_FILE.open("w") as fh:
        json.dump({"version": "1.0", "accounts": accounts}, fh, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Global Macro Sentiment — batch runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  python run.py                    normal run
  python run.py --sync-accounts    pull latest curated account list first
  python run.py --use-finbert      use FinBERT (better, ~420 MB first run)
  python run.py --no-browser       don't auto-open the report
  python run.py --skip-fintwit     skip Twitter/X entirely
""",
    )
    parser.add_argument(
        "--sync-accounts", action="store_true",
        help="Merge built-in curated account list into accounts.json before scraping.",
    )
    parser.add_argument(
        "--use-finbert", action="store_true",
        help="Use FinBERT for sentiment (downloads ~420 MB on first run).",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Generate the report but do not open it in the browser.",
    )
    parser.add_argument(
        "--skip-fintwit", action="store_true",
        help="Skip FinTwit / Nitter scraping (use when Nitter is unavailable).",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1. Accounts
    # ------------------------------------------------------------------
    accounts = _load_accounts()

    if args.sync_accounts:
        logger.info("Syncing accounts with curated list…")
        accounts = _sync_accounts(accounts)
        _save_accounts(accounts)

    active_accounts = [a for a in accounts if a.get("active", True)]
    logger.info(
        "Accounts: %d active / %d total",
        len(active_accounts), len(accounts),
    )

    # ------------------------------------------------------------------
    # 2. DB init
    # ------------------------------------------------------------------
    from src.db import init_db, save_run, get_history
    init_db()

    # ------------------------------------------------------------------
    # 3. Scrape
    # ------------------------------------------------------------------
    from src.scrapers.market import fetch_market_data, fetch_fear_greed
    from src.scrapers.liquidity import fetch_global_liquidity
    from src.scrapers.reddit import fetch_all as fetch_reddit
    from src.scrapers.news   import fetch_all as fetch_news

    logger.info("─── Market data ───────────────────────────────")
    market_data = fetch_market_data()
    fear_greed  = fetch_fear_greed()
    liquidity   = fetch_global_liquidity()

    ft_raw: list = []
    if not args.skip_fintwit:
        logger.info("─── FinTwit (Nitter RSS) ──────────────────────")
        from src.scrapers.fintwit import fetch_all as fetch_fintwit
        ft_raw = fetch_fintwit(active_accounts)
    else:
        logger.info("Skipping FinTwit (--skip-fintwit).")

    logger.info("─── Reddit ─────────────────────────────────────")
    rd_raw = fetch_reddit()

    logger.info("─── News RSS ───────────────────────────────────")
    nw_raw = fetch_news()

    # ------------------------------------------------------------------
    # 4. Sentiment analysis
    # ------------------------------------------------------------------
    from src.sentiment import analyze_batch, aggregate_sentiment

    engine = "FinBERT" if args.use_finbert else "VADER"
    logger.info("─── Sentiment analysis (%s) ────────────────────", engine)

    ft_posts = analyze_batch(ft_raw, use_finbert=args.use_finbert)
    rd_posts = analyze_batch(rd_raw, use_finbert=args.use_finbert)
    nw_posts = analyze_batch(nw_raw, use_finbert=args.use_finbert)

    for p in ft_posts: p["source_type"] = "fintwit"
    for p in rd_posts: p["source_type"] = "reddit"
    for p in nw_posts: p["source_type"] = "news"

    all_posts = ft_posts + rd_posts + nw_posts

    ft_agg = aggregate_sentiment(ft_posts)
    rd_agg = aggregate_sentiment(rd_posts)
    nw_agg = aggregate_sentiment(nw_posts)
    ov_agg = aggregate_sentiment(all_posts)

    summary = {
        "overall": ov_agg,
        "fintwit": ft_agg,
        "reddit":  rd_agg,
        "news":    nw_agg,
        "liquidity": liquidity,
    }

    logger.info(
        "Scores — Overall: %+.3f  |  FinTwit: %+.3f  |  Reddit: %+.3f  |  News: %+.3f",
        ov_agg["mean"], ft_agg["mean"], rd_agg["mean"], nw_agg["mean"],
    )

    # ------------------------------------------------------------------
    # 5. Persist
    # ------------------------------------------------------------------
    run_id  = save_run(summary, all_posts)
    history = get_history()
    logger.info("Saved run #%d to database.", run_id)

    # ------------------------------------------------------------------
    # 6. Generate report
    # ------------------------------------------------------------------
    from src.report import generate_report

    logger.info("─── Generating report ──────────────────────────")
    report_path = generate_report(
        market_data   = market_data,
        fear_greed    = fear_greed,
        liquidity     = liquidity,
        fintwit_posts = ft_posts,
        reddit_posts  = rd_posts,
        news_posts    = nw_posts,
        summary       = summary,
        history       = history,
    )

    logger.info("Done!  Report → %s", report_path)

    if not args.no_browser:
        webbrowser.open(f"file://{report_path.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
