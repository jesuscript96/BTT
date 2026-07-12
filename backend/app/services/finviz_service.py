"""
Finviz Elite export API client (official, paid — replaces Finviz scraping).

Three CSV endpoints, all authenticated with FINVIZ_API_KEY:
  * /export       — screener rows; with `t=<ticker>` + `c=` returns a single row
                    with any of ~110 fundamental/technical columns.
  * /news_export  — per-ticker news (title, source, datetime, url).
  * /quote_export — OHLCV candles (p=i1 minute incl. premarket, p=d daily).

Parsing is by HEADER NAME, never by column position, so a Finviz-side column
reshuffle can't corrupt us. Units: Market Cap / Shares / Short Interest come in
millions; ownership and short-float come as percentages ("12.4%") and are
normalized to fractions (0-1) to match alphavantage_service's contract.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("btt.finviz")

API_KEY = os.getenv("FINVIZ_API_KEY", "")
BASE = "https://elite.finviz.com"
TIMEOUT = 8.0

# In-memory TTL cache for snapshots: the sync path and the background
# enrichment both want the same row within seconds — one HTTP call must serve
# both (Finviz 429s on bursts of ~5 rapid requests). Negative results are
# cached too so uncovered/delisted tickers don't re-hit the API on every view.
_SNAP_TTL = 600.0  # seconds
_snap_cache: Dict[str, tuple] = {}  # ticker -> (expiry_ts, snapshot|None)
_snap_lock = threading.Lock()

# Columns requested from /export (v=152). Values are Finviz `c=` ids; we still
# parse by header name — this list only controls what Finviz sends back.
_EXPORT_COLS = "1,2,3,4,5,6,24,25,26,28,30,31,63,64,65,66,67,76,81,84"


def _to_float(v: Any) -> Optional[float]:
    """'147.03%' → 147.03 · '1,234.5' → 1234.5 · '-'/'' → None."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "").rstrip("%")
    if not s or s in ("-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _millions(v: Any) -> Optional[float]:
    f = _to_float(v)
    return f * 1_000_000 if f is not None else None


def _fraction(v: Any) -> Optional[float]:
    f = _to_float(v)
    return f / 100.0 if f is not None else None


def _get_csv(path: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
    """GET a Finviz export endpoint and parse the CSV into dict rows."""
    if not API_KEY:
        return []
    params = {**params, "auth": API_KEY}
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        resp = client.get(f"{BASE}{path}", params=params)
        resp.raise_for_status()
    text = resp.text.strip()
    if not text or text.startswith("<"):  # HTML = auth/HTML error page, not CSV
        return []
    return list(csv.DictReader(io.StringIO(text)))


def get_snapshot(ticker: str) -> Optional[Dict[str, Any]]:
    """One-call fundamental snapshot. Shape mirrors alphavantage_service
    .get_overview (float_shares, held_percent_*, sector/industry/country...)
    plus name / short_float / short_interest / prices. None if no coverage."""
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return None
    now = time.time()
    with _snap_lock:
        hit = _snap_cache.get(ticker)
        if hit and hit[0] > now:
            return hit[1]
    try:
        rows = _get_csv("/export", {"v": 152, "t": ticker, "c": _EXPORT_COLS})
    except Exception as e:  # noqa: BLE001
        logger.warning("[FINVIZ] snapshot failed for %s: %s", ticker, e)
        return None  # transient (429/red): NOT cached, next call retries
    row = next((r for r in rows if r.get("Ticker", "").upper() == ticker), None)
    if row is None:
        with _snap_lock:
            _snap_cache[ticker] = (now + _SNAP_TTL, None)  # no coverage: cache it
        return None
    snap = {
        "name": (row.get("Company") or "").strip() or None,
        "sector": (row.get("Sector") or "").strip() or None,
        "industry": (row.get("Industry") or "").strip() or None,
        "country": (row.get("Country") or "").strip() or None,
        "market_cap": _millions(row.get("Market Cap")),
        "shares_outstanding": _millions(row.get("Shares Outstanding")),
        "float_shares": _millions(row.get("Shares Float")),
        "held_percent_insiders": _fraction(row.get("Insider Ownership")),
        "held_percent_institutions": _fraction(row.get("Institutional Ownership")),
        "short_float_pct": _to_float(row.get("Short Float")),        # already a %
        "short_interest": _millions(row.get("Short Interest")),
        "avg_volume": _millions(row.get("Average Volume")),
        "rel_volume": _to_float(row.get("Relative Volume")),
        "price": _to_float(row.get("Price")),
        "change_pct": _to_float(row.get("Change")),
        "volume": _to_float(row.get("Volume")),
        "prev_close": _to_float(row.get("Prev Close")),
        "employees": _to_float(row.get("Employees")),
    }
    # Coverage check: a row with a ticker but no fundamentals is useless.
    if all(snap[k] is None for k in ("market_cap", "float_shares", "shares_outstanding", "price")):
        snap = None
    with _snap_lock:
        _snap_cache[ticker] = (now + _SNAP_TTL, snap)
    return snap


def get_news(ticker: str, limit: int = 30) -> List[Dict[str, str]]:
    """Per-ticker news. Returns [{title, source, date, url}] (newest first)."""
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return []
    try:
        rows = _get_csv("/news_export", {"v": 3, "t": ticker})
    except Exception as e:  # noqa: BLE001
        logger.warning("[FINVIZ] news failed for %s: %s", ticker, e)
        return []
    return [
        {
            "title": r.get("Title", ""),
            "source": r.get("Source", ""),
            "date": r.get("Date", ""),
            "url": r.get("Url", ""),
        }
        for r in rows[:limit]
        if r.get("Title")
    ]


def _fmt_millions(v: Optional[float]) -> str:
    if v is None:
        return "-"
    if v >= 1e9:
        return f"{v / 1e9:.2f}B"
    return f"{v / 1e6:.2f}M"


def get_float_row(ticker: str) -> Optional[Dict[str, str]]:
    """Float/short/outstanding formatted for the 'Know The Float' table
    (same string shape the knowthefloat scraper produces per source)."""
    snap = get_snapshot(ticker)
    if not snap:
        return None
    sf = snap.get("short_float_pct")
    return {
        "float": _fmt_millions(snap.get("float_shares")),
        "short_percent": f"{sf:.1f}%" if sf is not None else "-",
        "outstanding": _fmt_millions(snap.get("shares_outstanding")),
    }
