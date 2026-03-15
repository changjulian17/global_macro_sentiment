"""SQLite persistence layer.

Stores one row per run with aggregate scores, and the raw scored posts so you
can query history or drill down later.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "sentiment.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                run_time      TEXT    NOT NULL,
                overall_score REAL,
                fintwit_score REAL,
                reddit_score  REAL,
                news_score    REAL,
                summary_json  TEXT
            );

            CREATE TABLE IF NOT EXISTS posts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      INTEGER NOT NULL,
                source_type TEXT,
                source      TEXT,
                text        TEXT,
                url         TEXT,
                published   TEXT,
                score       REAL,
                label       TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_runs_time ON runs(run_time);
            CREATE INDEX IF NOT EXISTS idx_posts_run ON posts(run_id);
            """
        )


def save_run(summary: dict, posts: list) -> int:
    """Persist a run and its posts.  Returns the new run ID."""
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO runs (run_time, overall_score, fintwit_score,
                              reddit_score, news_score, summary_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                summary.get("overall", {}).get("mean", 0),
                summary.get("fintwit", {}).get("mean", 0),
                summary.get("reddit",  {}).get("mean", 0),
                summary.get("news",    {}).get("mean", 0),
                json.dumps(summary),
            ),
        )
        run_id = cur.lastrowid
        conn.executemany(
            """
            INSERT INTO posts
              (run_id, source_type, source, text, url, published, score, label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    p.get("source_type", ""),
                    p.get("source", ""),
                    p.get("text", "")[:2000],
                    p.get("url", ""),
                    p.get("published", ""),
                    p.get("score", 0.0),
                    p.get("label", "neutral"),
                )
                for p in posts
            ],
        )
    logger.debug("Saved run #%d (%d posts)", run_id, len(posts))
    return run_id


def get_history(limit: int = 60) -> list[dict]:
    """Return the most recent *limit* runs, oldest-first."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT run_time, overall_score, fintwit_score, reddit_score, news_score
            FROM   runs
            ORDER  BY run_time DESC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()
    return list(reversed([dict(r) for r in rows]))
