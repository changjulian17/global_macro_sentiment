#!/usr/bin/env python3
"""Manage the FinTwit account list (config/accounts.json).

Usage
-----
  python manage_accounts.py list
  python manage_accounts.py add <username> [--name "Full Name"] [--category macro]
  python manage_accounts.py remove <username>
  python manage_accounts.py enable  <username>
  python manage_accounts.py disable <username>
  python manage_accounts.py import  accounts.txt     # one username per line

Categories
----------
  macro  hedge_fund  fixed_income  equities  fx  commodities  crypto
  technicals  news  tech_macro  other
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ACCOUNTS_FILE = Path(__file__).parent / "config" / "accounts.json"

CATEGORIES = [
    "macro", "hedge_fund", "fixed_income", "equities", "fx",
    "commodities", "crypto", "technicals", "news", "tech_macro", "other",
]


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _load() -> list:
    if not ACCOUNTS_FILE.exists():
        return []
    with ACCOUNTS_FILE.open() as fh:
        return json.load(fh).get("accounts", [])


def _save(accounts: list) -> None:
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version":      "1.0",
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "accounts":     accounts,
    }
    with ACCOUNTS_FILE.open("w") as fh:
        json.dump(data, fh, indent=2)
    print(f"Saved {len(accounts)} accounts → {ACCOUNTS_FILE}")


def _strip(username: str) -> str:
    return username.lstrip("@").strip()


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    accounts = _load()
    if not accounts:
        print("No accounts yet.  Try: python manage_accounts.py add <username>")
        return 0

    sorted_accounts = sorted(
        accounts,
        key=lambda a: (a.get("category", ""), a["username"].lower()),
    )
    W = 22
    print(f"\n{'USERNAME':<{W}} {'NAME':<32} {'CATEGORY':<16} STATUS")
    print("─" * 84)
    active_count = 0
    for a in sorted_accounts:
        is_active = a.get("active", True)
        status = "✓  active" if is_active else "   disabled"
        if is_active:
            active_count += 1
        print(
            f"@{a['username']:<{W-1}} "
            f"{a.get('name',''):<32} "
            f"{a.get('category',''):<16} "
            f"{status}"
        )
    print(f"\n  {active_count} active / {len(accounts)} total\n")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    username = _strip(args.username)
    accounts = _load()
    existing = {a["username"].lower() for a in accounts}

    if username.lower() in existing:
        print(f"@{username} is already in the list.")
        # Re-enable if disabled
        for a in accounts:
            if a["username"].lower() == username.lower() and not a.get("active", True):
                a["active"] = True
                _save(accounts)
                print(f"  → Re-enabled @{username}.")
        return 0

    new = {
        "username": username,
        "name":     args.name or username,
        "category": args.category,
        "active":   True,
    }
    accounts.append(new)
    _save(accounts)
    print(f"Added @{username} ({new['name']}) [{args.category}]")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    username = _strip(args.username)
    accounts = _load()
    before   = len(accounts)
    accounts = [a for a in accounts if a["username"].lower() != username.lower()]
    if len(accounts) == before:
        print(f"@{username} not found.")
        return 1
    _save(accounts)
    print(f"Removed @{username}.")
    return 0


def _toggle(username: str, active: bool) -> int:
    username = _strip(username)
    accounts = _load()
    for a in accounts:
        if a["username"].lower() == username.lower():
            a["active"] = active
            _save(accounts)
            print(f"@{username} {'enabled' if active else 'disabled'}.")
            return 0
    print(f"@{username} not found.")
    return 1


def cmd_enable(args: argparse.Namespace) -> int:
    return _toggle(args.username, True)


def cmd_disable(args: argparse.Namespace) -> int:
    return _toggle(args.username, False)


def cmd_import(args: argparse.Namespace) -> int:
    """Import usernames from a plain-text file (one @username per line)."""
    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}")
        return 1
    accounts  = _load()
    existing  = {a["username"].lower() for a in accounts}
    added     = 0
    for raw_line in path.read_text().splitlines():
        username = _strip(raw_line.split()[0]) if raw_line.strip() else ""
        if not username or username.startswith("#"):
            continue
        if username.lower() in existing:
            continue
        accounts.append({
            "username": username,
            "name":     username,
            "category": args.category,
            "active":   True,
        })
        existing.add(username.lower())
        added += 1
    _save(accounts)
    print(f"Imported {added} new accounts from {path}.")
    return 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="manage_accounts",
        description="Manage FinTwit accounts tracked by the macro sentiment tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  python manage_accounts.py list
  python manage_accounts.py add druckenmiller --name "Stan Druckenmiller" --category macro
  python manage_accounts.py add elonmusk
  python manage_accounts.py disable zerohedge
  python manage_accounts.py enable  zerohedge
  python manage_accounts.py remove  someaccount
  python manage_accounts.py import  my_list.txt      # bulk import
""",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("list", help="Show all tracked accounts")

    p_add = sub.add_parser("add", help="Add a new account")
    p_add.add_argument("username",    help="Twitter/X handle (@ optional)")
    p_add.add_argument("--name",      default="", help="Display name")
    p_add.add_argument(
        "--category", default="macro", choices=CATEGORIES,
        help="Account category  [default: macro]",
    )

    p_rm = sub.add_parser("remove", help="Permanently remove an account")
    p_rm.add_argument("username")

    p_en = sub.add_parser("enable",  help="Re-enable a disabled account")
    p_en.add_argument("username")

    p_dis = sub.add_parser("disable", help="Disable without removing")
    p_dis.add_argument("username")

    p_imp = sub.add_parser("import", help="Bulk-import from a text file")
    p_imp.add_argument("file", help="Path to text file (one username per line)")
    p_imp.add_argument(
        "--category", default="macro", choices=CATEGORIES,
        help="Category for all imported accounts  [default: macro]",
    )

    args = parser.parse_args()

    dispatch = {
        "list":    cmd_list,
        "add":     cmd_add,
        "remove":  cmd_remove,
        "enable":  cmd_enable,
        "disable": cmd_disable,
        "import":  cmd_import,
    }

    if args.command not in dispatch:
        parser.print_help()
        return 1

    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
