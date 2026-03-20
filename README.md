# Global Macro Sentiment

Local batch pipeline for global macro sentiment using:
- FinTwit (via public Nitter RSS, no X API key)
- Reddit JSON or OAuth API
- News RSS feeds
- Market data from Yahoo Finance (`yfinance`)

Output:
- HTML dashboard: `reports/latest.html`
- Historical storage: `data/sentiment.db`

---

## 1) One-time setup

From project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Verify Python is using virtual env:

```bash
which python
```

Expected path contains `.venv/bin/python`.

---

## 2) Required checks before **any** run

Run these checks in order every time before a normal batch run.

### Check A: Environment + imports

```bash
source .venv/bin/activate
python -c "import requests, feedparser, yfinance, vaderSentiment; print('imports ok')"
```

Pass condition:
- Prints `imports ok`

### Check B: Unit tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_*.py' -v
```

Pass condition:
- Ends with `OK` (or expected `skipped` for live network test if Nitter is down)

### Check C: Accounts file sanity

```bash
source .venv/bin/activate
python manage_accounts.py list
```

Pass condition:
- Shows active accounts and no crash

### Check D: Preflight dry run (recommended)

This verifies the pipeline can complete end-to-end without relying on FinTwit uptime.

```bash
source .venv/bin/activate
python run.py --skip-fintwit --no-browser
```

Pass condition:
- Finishes with `Done!  Report -> .../reports/latest.html`

If all checks pass, proceed to default run.

---

## 3) Default run

```bash
source .venv/bin/activate
python run.py
```

This:
- Scrapes FinTwit + Reddit + News + Market data
- Scores sentiment
- Saves run to SQLite
- Opens the newest timestamped report file

---

## 4) Common run modes

### Sync curated account list before run

```bash
source .venv/bin/activate
python run.py --sync-accounts
```

### Run without opening browser

```bash
source .venv/bin/activate
python run.py --no-browser
```

### Skip FinTwit (when Nitter instances are unavailable)

```bash
source .venv/bin/activate
python run.py --skip-fintwit
```

### Use FinBERT sentiment model (optional)

First enable in `requirements.txt`:
- uncomment `transformers`
- uncomment `torch`

Then install and run:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python run.py --use-finbert
```

---

## 5) FinTwit account management

List accounts:

```bash
python manage_accounts.py list
```

Add account:

```bash
python manage_accounts.py add druckenmiller --name "Stan Druckenmiller" --category macro
```

Disable or re-enable:

```bash
python manage_accounts.py disable zerohedge
python manage_accounts.py enable zerohedge
```

Bulk import (one username per line):

```bash
python manage_accounts.py import my_accounts.txt --category macro
```

Notes:
- File: `config/accounts.json`
- Any account changes are picked up on next `python run.py`

---

## 6) Troubleshooting

### Tests pass but live FinTwit returns nothing

Cause:
- Public Nitter instances can be rate-limited or offline.

What to do:
1. Run with `--skip-fintwit`.
2. Update `NITTER_INSTANCES` in `src/scrapers/fintwit.py`.
3. Retry later.

### Reddit returns `403` in GitHub Actions

Cause:
- Reddit often blocks unauthenticated requests from datacenter IP ranges.

What to do:
1. Create a Reddit app at https://www.reddit.com/prefs/apps.
2. Add GitHub repository secrets `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`.
3. Re-run the Pages workflow.

Notes:
- The scraper uses OAuth automatically when those secrets are present.
- In GitHub Actions, if the secrets are missing, Reddit scraping is skipped
	with a single warning (instead of repeated 403 logs).
- Local runs can keep using public endpoints if they still work from your machine.

### Import errors

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Clean rebuild of venv

```bash
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 7) Fast command checklist

```bash
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_*.py' -v
python manage_accounts.py list
python run.py
```

---

## 8) Automatic daily scheduler (macOS)

Yes, this project now includes a `launchd` scheduler for macOS.

Behavior:
- Runs once at login (`RunAtLoad=true`) to catch missed runs
- Runs every day at 8:00 PM (`20:00`)
- Runs in background if your Mac is on and you are logged in
- Does not open a browser (`--no-browser`)

Install scheduler:

```bash
cd /Users/ju/Projects/global_macro_sentiment
scripts/install_launchd.sh
```

Verify scheduler is loaded:

```bash
launchctl print gui/$(id -u)/com.globalmacro.sentiment.daily | head -40
```

Trigger it immediately (manual test):

```bash
launchctl kickstart -k gui/$(id -u)/com.globalmacro.sentiment.daily
```

Check logs:

```bash
tail -n 100 logs/scheduler.log
tail -n 100 logs/launchd.stdout.log
tail -n 100 logs/launchd.stderr.log
```

Uninstall scheduler:

```bash
cd /Users/ju/Projects/global_macro_sentiment
scripts/uninstall_launchd.sh
```

Included scripts:
- `scripts/run_batch.sh` (actual background run command)
- `scripts/install_launchd.sh` (create + load launch agent)
- `scripts/uninstall_launchd.sh` (remove launch agent)

---

## 9) Free hosting on GitHub Pages (auto deploy)

This repo includes:
- `scripts/publish_pages.sh` — builds report and stages `docs/index.html`
- `.github/workflows/deploy-pages.yml` — deploys `docs/` to GitHub Pages

### One-time setup in GitHub

1. Push this repository to GitHub.
2. In GitHub repo settings, open **Pages**.
3. For source, select **GitHub Actions**.
4. In **Actions** tab, run workflow **Deploy Report to GitHub Pages** once.

After the first successful run, your report is live at:
- `https://changjulian17.github.io/global_macro_sentiment/`

### Automatic updates

The workflow runs:
- On every push to `main`
- On manual trigger (`workflow_dispatch`)
- Daily on schedule (`cron` in `.github/workflows/deploy-pages.yml`)

FinTwit behavior in workflow:
- Manual run: toggle `try_fintwit` input in Actions UI.
- If enabled, workflow tries with FinTwit first and automatically falls back to
	`--skip-fintwit` if Nitter/FinTwit fetch fails.

Reddit behavior in workflow:
- GitHub-hosted runners may receive `403` from Reddit public endpoints.
- To avoid that, add repository secrets `REDDIT_CLIENT_ID` and
	`REDDIT_CLIENT_SECRET`.
- Optional: add `REDDIT_USER_AGENT` if you want to override the default
	User-Agent string.
- If Reddit secrets are not set, the workflow skips Reddit scraping and still
	builds/deploys the report.

No manual commit is required for each report update when using this workflow.

### Keep local scheduler + auto commit/push after each run

The macOS `launchd` scheduler now supports a publish mode that:
1. Generates report + `docs/index.html`
2. Commits updated docs files
3. Pushes to `origin/main`

Reinstall launchd job to ensure latest settings are loaded:

```bash
cd /Users/ju/Projects/global_macro_sentiment
scripts/install_launchd.sh
```

If push auth fails in background runs, verify your git credential helper works
outside terminal prompts (Keychain/credential manager).

### GitHub-only mode (no local refresh dependency)

If you want to rely only on GitHub Actions scheduled runs:

```bash
cd /Users/ju/Projects/global_macro_sentiment
scripts/uninstall_launchd.sh
```

Then the Pages site updates from workflow schedule/manual/push only.

### Local dry run of publish script

```bash
source .venv/bin/activate
bash scripts/publish_pages.sh

# Force skip FinTwit
TRY_FINTWIT=false bash scripts/publish_pages.sh
```

Output:
- `docs/index.html` (the file GitHub Pages serves)
