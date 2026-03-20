"""HTML report generator.

Produces a self-contained dashboard saved to ``reports/latest.html``.
Charts are rendered via Chart.js loaded from jsDelivr CDN.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).parent.parent / "reports"

# Category display order for the market table
_CAT_ORDER = [
  "equities", "volatility", "rates", "credit", "fx", "commodities", "crypto", "international"
]

_HIGHLIGHT_TICKERS = {"^VIX", "^MOVE", "DX-Y.NYB", "DGS10"}


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _score_color(score: float) -> str:
    if score >= 0.3:
        return "#3fb950"
    if score <= -0.3:
        return "#f85149"
    return "#8b949e"


def _fg_color(value: int) -> str:
    if value >= 75:
        return "#3fb950"
    if value >= 55:
        return "#d29922"
    if value >= 45:
        return "#8b949e"
    if value >= 25:
        return "#d29922"
    return "#f85149"


# ---------------------------------------------------------------------------
# Component builders
# ---------------------------------------------------------------------------

def _pct_bar(bull: float, neut: float, bear: float) -> str:
    return (
        f'<div class="pct-bar">'
        f'<div class="seg bull" style="width:{bull:.1f}%" title="Bullish {bull:.1f}%"></div>'
        f'<div class="seg neut" style="width:{neut:.1f}%" title="Neutral {neut:.1f}%"></div>'
        f'<div class="seg bear" style="width:{bear:.1f}%" title="Bearish {bear:.1f}%"></div>'
        f"</div>"
    )


def _fmt_chg(
  v: float,
  delta_unit: str = "pct",
  max_abs_pct: float = 1.0,
  special: str = "",
) -> str:
    color = "#3fb950" if v >= 0 else "#f85149"
    sign = "+" if v >= 0 else ""

    if delta_unit == "bps":
        return f'<span style="color:{color};font-weight:600">{sign}{v:.1f} bps</span>'

    intensity = min(0.92, 0.18 + 0.72 * (abs(v) / max(max_abs_pct, 0.01)) ** 0.70)
    if v >= 0:
        bg = f"rgba(63,185,80,{intensity:.3f})"
        fg = "#e9fff0"
    else:
        bg = f"rgba(248,81,73,{intensity:.3f})"
        fg = "#fff1f0"

    accent = ""
    if special == "top":
        accent = " border:1px solid #f2cc60; box-shadow: inset 0 0 0 1px #f2cc6044;"
    elif special == "bottom":
        accent = " border:1px solid #79c0ff; box-shadow: inset 0 0 0 1px #79c0ff44;"

    tag = ""
    if special == "top":
        tag = " <span style='font-size:9px;font-weight:700;opacity:.9'>TOP5</span>"
    elif special == "bottom":
        tag = " <span style='font-size:9px;font-weight:700;opacity:.9'>BOT5</span>"

    return (
        f"<span style=\"display:inline-block;min-width:84px;text-align:right;"
        f"padding:1px 6px;border-radius:4px;font-weight:700;color:{fg};"
        f"background:{bg};{accent}\">{sign}{v:.2f}%{tag}</span>"
    )


def _market_rows(market_data: dict) -> str:
    html = ""
    pct_cells = []
    for a in market_data.values():
        if a.get("delta_unit", "pct") != "pct":
            continue
        ticker = a.get("ticker", "")
        for key in ("change_1d", "change_5d", "change_1mo"):
            val = float(a.get(key, 0.0) or 0.0)
            pct_cells.append((ticker, key, val))

    max_abs_pct = max([abs(v) for _, _, v in pct_cells], default=1.0)
    top5 = {(t, k) for t, k, _ in sorted(pct_cells, key=lambda x: x[2], reverse=True)[:5]}
    bot5 = {(t, k) for t, k, _ in sorted(pct_cells, key=lambda x: x[2])[:5]}

    for cat in _CAT_ORDER:
        assets = [a for a in market_data.values() if a.get("category") == cat]
        if not assets:
            continue
        html += f'<tr class="cat-hdr"><td colspan="6">{cat.upper()}</td></tr>\n'
        for a in assets:
            price = a.get("price", 0)
            ticker = a.get("ticker", "")
            level_unit = a.get("value_unit", "price")
            delta_unit = a.get("delta_unit", "pct")
            if level_unit == "yield_pct":
                price_str = f"{price:.3f}%"
            elif level_unit == "spread_bps":
                price_str = f"{price:.1f} bps"
            else:
                price_str = f"{price:,.4f}" if price < 10 else (
                    f"{price:,.2f}" if price < 100_000 else f"{price:,.0f}"
                )
            key_row = ticker in _HIGHLIGHT_TICKERS
            row_class = " class='key-row'" if key_row else ""
            name_cell = a.get("name", ticker)
            if key_row:
                name_cell = f'{name_cell} <span class="key-pill">KEY</span>'
            html += (
                f"<tr{row_class}>"
                f"<td>{name_cell}</td>"
                f"<td class='mono'>{ticker}</td>"
                f"<td class='num'>{price_str}</td>"
                f"<td class='num'>{_fmt_chg(a.get('change_1d', 0), delta_unit, max_abs_pct, 'top' if (ticker, 'change_1d') in top5 else ('bottom' if (ticker, 'change_1d') in bot5 else ''))}</td>"
                f"<td class='num'>{_fmt_chg(a.get('change_5d', 0), delta_unit, max_abs_pct, 'top' if (ticker, 'change_5d') in top5 else ('bottom' if (ticker, 'change_5d') in bot5 else ''))}</td>"
                f"<td class='num'>{_fmt_chg(a.get('change_1mo', 0), delta_unit, max_abs_pct, 'top' if (ticker, 'change_1mo') in top5 else ('bottom' if (ticker, 'change_1mo') in bot5 else ''))}</td>"
                f"</tr>\n"
            )
    return html


def _post_cards(posts: list, n: int, ascending: bool = False) -> str:
    if not posts:
        return '<p class="muted">No data available.</p>'
    sorted_posts = sorted(posts, key=lambda x: x.get("score", 0), reverse=not ascending)[:n]
    cards = []
    for p in sorted_posts:
        score    = p.get("score", 0.0)
        label    = p.get("label", "neutral").upper()
        color    = _score_color(score)
        src_type = p.get("source_type", "")
        source   = p.get("source", "?")
        prefix   = "@" if src_type == "fintwit" else ("r/" if src_type == "reddit" else "")
        text     = (p.get("text", "")[:300] + "…") if len(p.get("text","")) > 300 else p.get("text","")
        url      = p.get("url", "")
        link_html = f'<a href="{url}" target="_blank" class="post-link">View →</a>' if url else ""
        cards.append(
            f'<div class="post">'
            f'<div class="post-meta">'
            f'<span class="badge" style="background:{color}22;color:{color};'
            f'border:1px solid {color}55">{label}</span>'
            f'<span class="post-src">{prefix}{source}</span>'
            f'<span class="post-score mono" style="color:{color}">{score:+.3f}</span>'
            f"</div>"
            f'<div class="post-text">{text}</div>'
            f"{link_html}"
            f"</div>"
        )
    return "\n".join(cards)


def _source_card(title: str, agg: dict) -> str:
    mean  = agg.get("mean", 0.0)
    color = _score_color(mean)
    return (
        f'<div class="card">'
        f'<h2>{title}</h2>'
        f'<div class="big-num" style="color:{color}">{mean:+.3f}</div>'
        f'{_pct_bar(agg.get("bullish_pct",0), agg.get("neutral_pct",0), agg.get("bearish_pct",0))}'
        f'<div class="stat-row">'
        f'<span style="color:#3fb950">▲ {agg.get("bullish_pct",0):.1f}%</span>'
        f'<span style="color:#8b949e">● {agg.get("neutral_pct",0):.1f}%</span>'
        f'<span style="color:#f85149">▼ {agg.get("bearish_pct",0):.1f}%</span>'
        f'</div>'
        f'<div class="muted" style="margin-top:4px">{agg.get("count",0)} items</div>'
        f"</div>"
    )


def _fg_card(title: str, fg: dict) -> str:
    val   = fg.get("value", "N/A")
    lbl   = fg.get("label", "Unknown")
    color = _fg_color(int(val)) if isinstance(val, int) else "#8b949e"
    return (
        f'<div class="card">'
        f"<h2>{title}</h2>"
        f'<div style="text-align:center;padding:16px 0">'
        f'<div class="big-num" style="color:{color};font-size:52px">{val}</div>'
        f'<div style="color:{color};margin-top:4px;font-weight:600">{lbl}</div>'
        f"</div>"
        f"</div>"
    )


def _liq_card(title: str, liq: dict) -> str:
    val = liq.get("score")
    lbl = liq.get("label", "Unknown")
    comp = liq.get("composite_z")

    if isinstance(val, (int, float)):
        val_i = round(float(val))
        color = _fg_color(val_i)
        val_html = f"{float(val):.1f}"
        comp_html = f"Composite z-score: {float(comp):+.3f}" if isinstance(comp, (int, float)) else ""
    else:
        color = "#8b949e"
        val_html = "N/A"
        comp_html = ""

    return (
        f'<div class="card">'
        f"<h2>{title}</h2>"
        f'<div style="text-align:center;padding:16px 0">'
        f'<div class="big-num" style="color:{color};font-size:52px">{val_html}</div>'
        f'<div style="color:{color};margin-top:4px;font-weight:600">{lbl}</div>'
        f"</div>"
        f'<div class="muted" style="text-align:center">{comp_html}</div>'
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Main report function
# ---------------------------------------------------------------------------

def generate_report(
    market_data: dict,
    fear_greed:  dict,
    liquidity:   dict,
    fintwit_posts: list,
    reddit_posts:  list,
    news_posts:    list,
    summary:  dict,
    history:  list,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%d %H:%M UTC")

    overall = summary.get("overall", {})
    ov_score = overall.get("mean", 0.0)
    ov_color = _score_color(ov_score)
    ov_label = (
        "BULLISH" if ov_score >= 0.3 else ("BEARISH" if ov_score <= -0.3 else "NEUTRAL")
    )

    ft_agg = summary.get("fintwit", {})
    rd_agg = summary.get("reddit",  {})
    nw_agg = summary.get("news",    {})

    all_posts = fintwit_posts + reddit_posts + news_posts

    # History chart datasets (oldest -> newest)
    # Keep raw UTC timestamps so the browser can render them in local time.
    hist_run_times = [h.get("run_time", "") for h in history]
    hist_overall = [round(h.get("overall_score", 0) or 0, 4) for h in history]
    hist_ft      = [round(h.get("fintwit_score", 0) or 0, 4) for h in history]
    hist_rd      = [round(h.get("reddit_score",  0) or 0, 4) for h in history]
    hist_nw      = [round(h.get("news_score",    0) or 0, 4) for h in history]

    liq_hist = (liquidity or {}).get("history", {})
    liq_labels = liq_hist.get("dates", [])
    liq_scores = liq_hist.get("scores", [])

    # Y-axis: tight range from actual data min/max with 5% padding
    _all_vals = [v for v in hist_overall + hist_ft + hist_rd + hist_nw if v is not None]
    if len(_all_vals) >= 2:
        _pad = (max(_all_vals) - min(_all_vals)) * 0.05 or 0.01
        _y_min = round(min(_all_vals) - _pad, 4)
        _y_max = round(max(_all_vals) + _pad, 4)
    else:
        _y_min = -0.5
        _y_max = 0.5

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Global Macro Sentiment — {ts}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0d1117; color: #c9d1d9; font-size: 14px; line-height: 1.5;
  }}
  a {{ color: #58a6ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .wrap {{ max-width: 1440px; margin: 0 auto; padding: 20px 24px; }}
  header {{
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #30363d; padding-bottom: 16px; margin-bottom: 20px;
  }}
  header h1 {{ font-size: 20px; font-weight: 700; color: #f0f6fc; }}
  .ts {{ color: #8b949e; font-size: 12px; }}
  .grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 16px; }}
  .grid-2 {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-bottom: 16px; }}
  .card {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 18px;
    margin-bottom: 0;
  }}
  .card h2 {{
    font-size: 11px; font-weight: 600; color: #8b949e;
    text-transform: uppercase; letter-spacing: .08em; margin-bottom: 12px;
  }}
  .big-num {{ font-size: 42px; font-weight: 700; line-height: 1; margin-bottom: 8px; }}
  .pct-bar {{
    display: flex; height: 7px; border-radius: 4px; overflow: hidden;
    background: #21262d; margin: 8px 0 10px;
  }}
  .seg.bull {{ background: #3fb950; }}
  .seg.neut {{ background: #8b949e; }}
  .seg.bear {{ background: #f85149; }}
  .stat-row {{ display: flex; justify-content: space-between; font-size: 12px; }}
  .muted {{ color: #8b949e; font-size: 12px; }}
  .section {{ background: #161b22; border: 1px solid #30363d;
              border-radius: 8px; padding: 18px; margin-bottom: 16px; }}
  .section h2 {{
    font-size: 11px; font-weight: 600; color: #8b949e;
    text-transform: uppercase; letter-spacing: .08em; margin-bottom: 14px;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{
    text-align: left; font-size: 11px; font-weight: 500; color: #8b949e;
    padding: 5px 8px; border-bottom: 1px solid #30363d;
  }}
  td {{ padding: 5px 8px; border-bottom: 1px solid #21262d; }}
  td.num {{ text-align: right; }}
  td.mono {{ font-family: ui-monospace, monospace; font-size: 12px; color: #8b949e; }}
  tr.key-row td:first-child {{ font-weight: 700; color: #f0f6fc; }}
  tr.key-row td.mono {{ color: #c9d1d9; font-weight: 700; }}
  .key-pill {{
    display: inline-block; margin-left: 6px; padding: 0 6px;
    border-radius: 10px; font-size: 9px; font-weight: 800;
    color: #0d1117; background: #f2cc60; letter-spacing: .06em;
  }}
  tr.cat-hdr td {{
    background: #0d1117; color: #8b949e; font-size: 10px;
    font-weight: 700; letter-spacing: .1em; padding: 7px 8px 3px;
  }}
  .post {{
    background: #0d1117; border: 1px solid #21262d; border-radius: 6px;
    padding: 12px; margin-bottom: 10px;
  }}
  .post:last-child {{ margin-bottom: 0; }}
  .post-meta {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }}
  .post-text {{ color: #8b949e; font-size: 13px; line-height: 1.5; }}
  .badge {{
    font-size: 10px; font-weight: 700; padding: 1px 7px;
    border-radius: 10px; flex-shrink: 0;
  }}
  .post-src {{ font-size: 11px; color: #58a6ff; }}
  .post-score {{ font-size: 11px; }}
  .post-link {{ font-size: 11px; display: inline-block; margin-top: 5px; color: #58a6ff; }}
  .mono {{ font-family: ui-monospace, monospace; }}
  canvas {{ max-height: 260px; width: 100% !important; }}
  @media (max-width: 860px) {{
    .grid-3, .grid-2 {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <header>
    <h1>🌐 Global Macro Sentiment</h1>
    <span class="ts">Generated {ts}</span>
  </header>

  <!-- Row 1: Overall + F&G -->
  <div class="grid-3">
    <div class="card" style="border-left:3px solid {ov_color}">
      <h2>Overall Sentiment</h2>
      <div class="big-num" style="color:{ov_color}">{ov_score:+.3f}</div>
      <span class="badge" style="background:{ov_color}22;color:{ov_color};border:1px solid {ov_color}55">
        {ov_label}
      </span>
      {_pct_bar(overall.get('bullish_pct',0), overall.get('neutral_pct',0), overall.get('bearish_pct',0))}
      <div class="stat-row">
        <span style="color:#3fb950">▲ {overall.get('bullish_pct',0):.1f}%</span>
        <span style="color:#8b949e">● {overall.get('neutral_pct',0):.1f}%</span>
        <span style="color:#f85149">▼ {overall.get('bearish_pct',0):.1f}%</span>
      </div>
      <div class="muted" style="margin-top:5px">{overall.get('count',0)} items analyzed</div>
    </div>
    {_fg_card("Fear &amp; Greed — Crypto (alternative.me)", fear_greed.get("crypto_fg", {}))}
    {_fg_card("Fear &amp; Greed — Equities (CNN)", fear_greed.get("equity_fg", {}))}
  </div>

  <div class="grid-3" style="margin-top:-2px">
    {_liq_card("Global Liquidity (Fed+ECB+BoJ, USD-adjusted)", liquidity)}
  </div>

  <!-- Row 2: Source breakdown -->
  <div class="grid-3">
    {_source_card("FinTwit Sentiment", ft_agg)}
    {_source_card("Reddit Sentiment", rd_agg)}
    {_source_card("News Sentiment", nw_agg)}
  </div>

  <!-- Sentiment history chart -->
  <div class="section">
    <h2>Sentiment History (last {len(history)} runs)</h2>
    <canvas id="histChart"></canvas>
  </div>

  <div class="section">
    <h2>Global Liquidity History (weekly, last {len(liq_labels)} points)</h2>
    <canvas id="liqChart"></canvas>
  </div>

  <!-- Top bullish / bearish posts -->
  <div class="grid-2">
    <div class="card">
      <h2>🟢 Most Bullish Signals</h2>
      {_post_cards(all_posts, n=6, ascending=False)}
    </div>
    <div class="card">
      <h2>🔴 Most Bearish Signals</h2>
      {_post_cards(all_posts, n=6, ascending=True)}
    </div>
  </div>

  <!-- FinTwit feed -->
  <div class="section" style="margin-top:16px">
    <h2>FinTwit — Latest Tweets</h2>
    {"" if fintwit_posts else '<p class="muted">No FinTwit data — Nitter instances may be unavailable. Try again later or check <code>src/scrapers/fintwit.py</code> NITTER_INSTANCES.</p>'}
    {_post_cards(fintwit_posts, n=15) if fintwit_posts else ""}
  </div>

  <!-- Reddit feed -->
  <div class="section">
    <h2>Reddit — Top Posts</h2>
    {_post_cards(reddit_posts, n=10)}
  </div>

  <!-- Market overview -->
  <div class="section">
    <h2>Market Overview</h2>
    <table>
      <thead>
        <tr>
          <th>Asset</th><th>Ticker</th>
          <th style="text-align:right">Price</th>
          <th style="text-align:right">1D</th>
          <th style="text-align:right">5D</th>
          <th style="text-align:right">1MO</th>
        </tr>
      </thead>
      <tbody>
        {_market_rows(market_data)}
      </tbody>
    </table>
  </div>

</div><!-- /wrap -->

<script>
(function() {{
  const ctx = document.getElementById('histChart');
  if (!ctx) return;
  const histRunTimes = {json.dumps(hist_run_times)};
  const parseUtcTimestamp = (value) => {{
    if (!value) return null;
    const hasTz = /Z$|[+\-]\d\d:\d\d$/.test(value);
    const normalized = hasTz ? value : `${{value.replace(' ', 'T')}}Z`;
    const dt = new Date(normalized);
    return Number.isNaN(dt.getTime()) ? null : dt;
  }};
  const dateFmt = new Intl.DateTimeFormat(undefined, {{
    year: '2-digit', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false
  }});
  const histDates = histRunTimes.map(parseUtcTimestamp);
  const histLabels = histDates.map((dt, idx) => dt ? dateFmt.format(dt) : (histRunTimes[idx] || ''));
  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: histLabels,
      datasets: [
        {{
          label: 'Overall',
          data: {json.dumps(hist_overall)},
          borderColor: '#58a6ff', backgroundColor: '#58a6ff18',
          fill: true, tension: 0.35, pointRadius: 3
        }},
        {{
          label: 'FinTwit',
          data: {json.dumps(hist_ft)},
          borderColor: '#bc8cff', fill: false, tension: 0.35, pointRadius: 2
        }},
        {{
          label: 'Reddit',
          data: {json.dumps(hist_rd)},
          borderColor: '#ff7b72', fill: false, tension: 0.35, pointRadius: 2
        }},
        {{
          label: 'News',
          data: {json.dumps(hist_nw)},
          borderColor: '#d29922', fill: false, tension: 0.35, pointRadius: 2
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: true,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#c9d1d9', font: {{ size: 12 }} }} }},
        tooltip: {{
          backgroundColor: '#161b22',
          borderColor: '#30363d',
          borderWidth: 1,
          callbacks: {{
            title: (items) => {{
              const idx = items && items.length ? items[0].dataIndex : -1;
              const dt = idx >= 0 ? histDates[idx] : null;
              return dt ? dt.toLocaleString() : (items && items.length ? items[0].label : '');
            }}
          }}
        }}
      }},
      scales: {{
        x: {{
          ticks: {{ color: '#8b949e', maxTicksLimit: 12, font: {{ size: 11 }} }},
          grid:  {{ color: '#21262d' }}
        }},
        y: {{
          min: {_y_min},
          max: {_y_max},
          ticks: {{ color: '#8b949e', maxTicksLimit: 8, font: {{ size: 11 }} }},
          grid:  {{ color: '#21262d' }},
          title: {{ display: true, text: 'Sentiment Score', color: '#8b949e', font: {{ size: 11 }} }}
        }}
      }}
    }}
  }});
}})();

(function() {{
  const ctx = document.getElementById('liqChart');
  if (!ctx) return;
  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: {json.dumps(liq_labels)},
      datasets: [
        {{
          label: 'Liquidity Score (0-100)',
          data: {json.dumps(liq_scores)},
          borderColor: '#3fb950',
          backgroundColor: '#3fb95022',
          fill: true,
          tension: 0.3,
          pointRadius: 2
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: true,
      plugins: {{
        legend: {{ labels: {{ color: '#c9d1d9', font: {{ size: 12 }} }} }},
        tooltip: {{ backgroundColor: '#161b22', borderColor: '#30363d', borderWidth: 1 }}
      }},
      scales: {{
        x: {{
          ticks: {{ color: '#8b949e', maxTicksLimit: 12, font: {{ size: 11 }} }},
          grid:  {{ color: '#21262d' }}
        }},
        y: {{
          min: 0,
          max: 100,
          ticks: {{ color: '#8b949e', maxTicksLimit: 8, font: {{ size: 11 }} }},
          grid:  {{ color: '#21262d' }},
          title: {{ display: true, text: 'Liquidity Score', color: '#8b949e', font: {{ size: 11 }} }}
        }}
      }}
    }}
  }});
}})();
</script>
</body>
</html>"""

    out = REPORTS_DIR / "latest.html"
    out.write_text(html, encoding="utf-8")

    logger.info("Report saved → %s", out)
    return out
