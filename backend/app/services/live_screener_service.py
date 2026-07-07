"""
Live screener service — real-time US stock screener fed by Massive's WebSocket.

Responsibilities (all in-process, no DB writes on the hot path):
  * Bootstrap a per-ticker state map from the REST snapshot (prev_close, last
    price, session volume) + an avg-20d-volume lookup from DuckDB (for RVol).
    The universe is an authoritative CS + ADRC allow-list built from the Massive
    reference API (refreshed daily); ETFs, warrants, units, rights, preferred,
    OTC, etc. are excluded, so they never reach the leaderboard.
  * Keep that state fresh by consuming Massive's second-aggregate stream
    (`A.*`) over `wss://socket.massive.com`. Each message is O(1): update last
    price, session high/low, accumulated volume and the RTH open.
  * On demand, `get_top(tab)` applies the official trading formulas (§3.2 of the
    PRD), filters (US + change >= ±15% for gainers/losers) and returns the top 50.
When the market is closed (or the WS can't connect / the account isn't live),
the REST snapshot poller keeps the map warm so the UI always has something to
show. This module is internal to the app backend — it is deliberately NOT part
of the commercial public API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

import httpx

try:  # websockets is provided by uvicorn[standard]; guard so import never breaks boot
    import websockets
except Exception:  # pragma: no cover
    websockets = None  # type: ignore

from dotenv import load_dotenv

load_dotenv()  # make MASSIVE_* available regardless of import order

logger = logging.getLogger("btt.live_screener")

# ─── Config ──────────────────────────────────────────────────────────────────
API_KEY = os.getenv("MASSIVE_API_KEY", "")
REST_BASE = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")
WS_URL = os.getenv("MASSIVE_WS_URL", "wss://socket.massive.com/stocks")

TOP_N = 50                   # rows streamed per tab
SNAPSHOT_POLL_SECONDS = 20   # REST fallback cadence while WS is down / market closed
TOP_CACHE_TTL = 1.0          # recompute a tab's leaderboard at most once per second

# Allow-list: only these instrument types reach the screener (PRD §02). The set
# is built from the Massive reference API and refreshed daily at this ET time.
ALLOWED_TYPES = ("CS", "ADRC")
ALLOWLIST_REFRESH_ET = dtime(4, 0)

ET = ZoneInfo("America/New_York")

# Session windows in Eastern Time.
PRE_OPEN, RTH_OPEN = dtime(4, 0), dtime(9, 30)
RTH_CLOSE, AFT_CLOSE = dtime(16, 0), dtime(20, 0)

# Tab identifiers shared with the frontend contract.
TAB_PRE = "Premarket"
TAB_GAINERS = "RTH Gainers"
TAB_LOSERS = "RTH Losers"
TAB_AFT = "Aftermarket"
VALID_TABS = {TAB_PRE, TAB_GAINERS, TAB_LOSERS, TAB_AFT}


def _f(v: Any) -> Optional[float]:
    """Coerce to a finite float or None."""
    try:
        if v is None:
            return None
        fv = float(v)
        if fv != fv or fv in (float("inf"), float("-inf")):
            return None
        return fv
    except (TypeError, ValueError):
        return None


@dataclass
class TickerLiveState:
    ticker: str
    name: str = ""
    exchange: str = ""
    # Day-level metrics — persist the whole day; reset ONLY on day change. These
    # are the source of truth for the "Top Gainers/Losers" tabs and let a ticker
    # stay visible across session boundaries (pre → rth → after).
    prev_close: Optional[float] = None       # prevDay.c  → base of day_change_pct
    rth_close: Optional[float] = None        # day.c (frozen at 16:00 ET) → base of after_pct
    day_open: Optional[float] = None         # day.o (RTH open)
    day_high: Optional[float] = None         # day.h
    day_low: Optional[float] = None          # day.l
    day_volume: float = 0.0                  # day.v
    last_price: Optional[float] = None       # lastTrade.p / WS `c`
    avg_vol_20d: Optional[float] = None
    # Per-session accumulators — only filled during their own window, so the
    # Premarket/Aftermarket tabs reflect what is moving NOW, not the whole day.
    after_volume: float = 0.0
    after_high: Optional[float] = None
    after_low: Optional[float] = None
    pre_volume: float = 0.0
    pre_high: Optional[float] = None
    updated_at: float = field(default_factory=time.time)


def current_session(now_et: Optional[datetime] = None) -> str:
    """Return the active US market session: 'pre' | 'rth' | 'after' | 'closed'."""
    dt = now_et or datetime.now(ET)
    if dt.weekday() >= 5:  # Sat/Sun
        return "closed"
    now = dt.timetz().replace(tzinfo=None)
    if PRE_OPEN <= now < RTH_OPEN:
        return "pre"
    if RTH_OPEN <= now < RTH_CLOSE:
        return "rth"
    if RTH_CLOSE <= now < AFT_CLOSE:
        return "after"
    return "closed"


class LiveScreenerService:
    """Singleton holding live per-ticker state and the Massive WS consumer."""

    def __init__(self) -> None:
        self._states: Dict[str, TickerLiveState] = {}
        self._allowlist: Set[str] = set()  # authoritative CS+ADRC universe
        self._lock = threading.RLock()
        self._ws_connected = False
        self._bootstrapped = False
        self._stop = False
        self._session: str = current_session()
        self._top_cache: Dict[str, tuple] = {}  # tab -> (ts, rows)
        self._tasks: List[asyncio.Task] = []

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def start(self) -> None:
        """Warm the critical state fast (universe + REST snapshot) so the grid
        has data immediately, then launch the WS consumer + poller. The avg-20d
        volume table (RVol only, non-critical) loads in the background so a slow
        or contended DuckDB query can never delay the live stream."""
        if os.getenv("LIVE_SCREENER_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
            logger.info("[LIVE] screener disabled via LIVE_SCREENER_ENABLED")
            return
        await asyncio.to_thread(self._refresh_allowlist)
        try:
            await asyncio.to_thread(self._refresh_from_snapshot)
        except Exception as e:  # noqa: BLE001
            logger.warning("[LIVE] initial snapshot failed: %s", e)
        self._bootstrapped = True
        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._consume_massive_ws()),
            loop.create_task(self._poll_snapshot_loop()),
            loop.create_task(self._session_watch_loop()),
            loop.create_task(self._allowlist_refresh_loop()),
            loop.create_task(asyncio.to_thread(self._load_avg_volume)),
        ]
        logger.info("[LIVE] screener service started (%d tickers in universe)", len(self._states))

    async def stop(self) -> None:
        self._stop = True
        for t in self._tasks:
            t.cancel()

    @property
    def ws_connected(self) -> bool:
        return self._ws_connected

    @property
    def session(self) -> str:
        return self._session

    # ── allow-list (universe = CS + ADRC, authoritative) ─────────────────────
    def _fetch_allowlist(self) -> Tuple[Set[str], Dict[str, Tuple[str, str]]]:
        """Fetch the active CS + ADRC US-stock universe from the Massive
        reference API (paginated via next_url). Returns (symbols, meta) where
        meta[ticker] = (name, primary_exchange). On any failure returns empties
        so the caller keeps the previous allow-list."""
        if not API_KEY:
            return set(), {}
        symbols: Set[str] = set()
        meta: Dict[str, Tuple[str, str]] = {}
        try:
            with httpx.Client(timeout=30.0) as client:
                for typ in ALLOWED_TYPES:
                    url: Optional[str] = f"{REST_BASE}/v3/reference/tickers"
                    params: Optional[Dict[str, Any]] = {
                        "market": "stocks", "active": "true", "type": typ,
                        "limit": 1000, "apiKey": API_KEY,
                    }
                    pages = 0
                    while url and pages < 50:  # ~7-8 pages expected; cap is a backstop
                        resp = client.get(url, params=params)
                        resp.raise_for_status()
                        data = resp.json()
                        for r in data.get("results") or []:
                            tk = str(r.get("ticker", "") or "")
                            if not tk:
                                continue
                            symbols.add(tk)
                            meta[tk] = (
                                str(r.get("name", "") or tk),
                                str(r.get("primary_exchange", "") or ""),
                            )
                        nxt = data.get("next_url")
                        # next_url already carries cursor + filters; only the key is missing.
                        url, params = (nxt, {"apiKey": API_KEY}) if nxt else (None, None)
                        pages += 1
            return symbols, meta
        except Exception as e:  # noqa: BLE001
            logger.warning("[LIVE] allow-list fetch failed (%s)", e)
            return set(), {}

    def _refresh_allowlist(self) -> None:
        """Rebuild the CS+ADRC allow-list and reconcile the universe: seed new
        tickers (name/exchange) and prune anything no longer allow-listed. Keeps
        the previous list if the fetch is empty; on a cold first failure, falls
        back to massive.tickers so the screener is never empty."""
        symbols, meta = self._fetch_allowlist()
        if not symbols:
            if self._allowlist:
                logger.warning("[LIVE] allow-list refresh failed; keeping previous (%d symbols)", len(self._allowlist))
            else:
                logger.warning("[LIVE] allow-list unavailable on first run; falling back to massive.tickers")
                self._load_universe()
            return
        with self._lock:
            self._allowlist = symbols
            for tk in symbols:
                name, exch = meta.get(tk, (tk, ""))
                st = self._states.get(tk)
                if st is None:
                    self._states[tk] = TickerLiveState(ticker=tk, name=name, exchange=exch)
                else:
                    if name:
                        st.name = name
                    if exch:
                        st.exchange = exch
            # Prune tickers that fell off the allow-list (delisted / re-typed).
            for tk in [t for t in self._states if t not in symbols]:
                del self._states[tk]
        logger.info("[LIVE] allow-list = %d CS+ADRC symbols (universe pruned to match)", len(symbols))

    def _load_universe(self) -> None:
        """Fallback universe from massive.tickers, used only when the REST
        allow-list is unavailable on a cold start (broader than CS+ADRC, but
        better than an empty screener)."""
        try:
            from app.services.cache_service import get_tickers_df

            df = get_tickers_df()
            loaded: Set[str] = set()
            with self._lock:
                for row in df.itertuples(index=False):
                    tk = str(getattr(row, "ticker", "") or "")
                    if not tk:
                        continue
                    loaded.add(tk)
                    if tk not in self._states:
                        self._states[tk] = TickerLiveState(
                            ticker=tk,
                            name=str(getattr(row, "name", "") or tk),
                            exchange=str(getattr(row, "primary_exchange", "") or ""),
                        )
                self._allowlist = loaded
            logger.info("[LIVE] fallback universe from massive.tickers: %d tickers", len(loaded))
        except Exception as e:  # noqa: BLE001
            logger.warning("[LIVE] fallback universe load failed (%s)", e)

    def _load_avg_volume(self) -> None:
        """20-day average RTH volume per ticker from daily_metrics (for RVol)."""
        try:
            from app.database import get_db_connection

            con = get_db_connection(read_only=True)
            try:
                rows = con.execute(
                    """
                    WITH recent AS (
                        SELECT ticker, rth_volume,
                               ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY timestamp DESC) AS rn
                        FROM daily_metrics
                        WHERE rth_volume IS NOT NULL AND rth_volume > 0
                    )
                    SELECT ticker, AVG(rth_volume) AS avg_vol
                    FROM recent WHERE rn <= 20 GROUP BY ticker
                    """
                ).fetchall()
            finally:
                con.close()
            with self._lock:
                for tk, avg_vol in rows:
                    st = self._states.get(str(tk))
                    if st:
                        st.avg_vol_20d = _f(avg_vol)
            logger.info("[LIVE] avg-20d volume loaded for %d tickers", len(rows))
        except Exception as e:  # noqa: BLE001
            logger.warning("[LIVE] avg-volume load failed (%s); RVol defaults to 1.0", e)

    # ── REST snapshot (bootstrap + fallback) ─────────────────────────────────
    def _refresh_from_snapshot(self) -> None:
        if not API_KEY:
            return
        url = f"{REST_BASE}/v2/snapshot/locale/us/markets/stocks/tickers"
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, params={"apiKey": API_KEY})
            resp.raise_for_status()
            payload = resp.json()
        tickers = payload.get("tickers") or []
        updated = 0
        with self._lock:
            for t in tickers:
                sym = str(t.get("ticker", ""))
                if not sym or sym not in self._allowlist:
                    continue  # allow-list gate: only CS + ADRC
                st = self._states.get(sym)
                if st is None:
                    st = TickerLiveState(ticker=sym)
                    self._states[sym] = st
                day = t.get("day") or {}
                prev = t.get("prevDay") or {}
                last = t.get("lastTrade") or {}
                mn = t.get("min") or {}
                st.prev_close = st.prev_close or _f(prev.get("c"))
                # day.c is frozen at the RTH close (verified: it does NOT track the
                # extended-hours last), so it is the correct base for after_pct.
                rthc = _f(day.get("c"))
                if rthc is not None:
                    st.rth_close = rthc
                st.last_price = _f(last.get("p")) or _f(mn.get("c")) or st.last_price
                st.day_volume = _f(day.get("v")) or st.day_volume or 0.0
                st.day_high = _f(day.get("h")) or st.day_high
                st.day_low = _f(day.get("l")) or st.day_low
                if st.day_open is None:
                    st.day_open = _f(day.get("o"))
                st.updated_at = time.time()
                updated += 1
        logger.info("[LIVE] snapshot refresh applied to %d tickers", updated)

    async def _poll_snapshot_loop(self) -> None:
        """Keep the map warm via REST while the WS is down in active sessions.
        When the market is closed, the last after-hours list stays frozen."""
        while not self._stop:
            try:
                await asyncio.sleep(SNAPSHOT_POLL_SECONDS)
                if self._session == "closed":
                    continue
                if self._ws_connected:
                    continue  # WS is the source of truth during live sessions
                await asyncio.to_thread(self._refresh_from_snapshot)
            except asyncio.CancelledError:  # pragma: no cover
                break
            except Exception as e:  # noqa: BLE001
                logger.debug("[LIVE] snapshot poll error: %s", e)

    async def _session_watch_loop(self) -> None:
        """Watch market-session boundaries and freeze/reset state as needed."""
        while not self._stop:
            try:
                await asyncio.sleep(30)
                await self._handle_session_transition(current_session())
            except asyncio.CancelledError:  # pragma: no cover
                break
            except Exception as e:  # noqa: BLE001
                logger.debug("[LIVE] session watch error: %s", e)

    async def _handle_session_transition(self, new_session: str) -> None:
        prev = self._session
        if new_session == prev:
            return
        self._session = new_session
        logger.info("[LIVE] session changed: %s -> %s", prev, new_session)
        # RTH → Aftermarket: freeze the RTH close (after_pct base) and start a
        # fresh after-hours accumulator. Day metrics are NOT reset.
        if prev == "rth" and new_session == "after":
            self._capture_rth_close()
            self._init_after_window()
        # Closed → any active session: a new trading day begins → reset the day.
        if prev == "closed" and new_session != "closed":
            logger.info("[LIVE] new trading day; resetting screener day metrics")
            await asyncio.to_thread(self._reset_day)

    def _capture_rth_close(self) -> None:
        with self._lock:
            for st in self._states.values():
                if st.last_price is not None:
                    st.rth_close = st.last_price

    def _init_after_window(self) -> None:
        """Start a fresh after-hours accumulator (volume/high/low). Called on the
        rth→after transition; day-level metrics are left untouched."""
        with self._lock:
            for st in self._states.values():
                st.after_volume = 0.0
                st.after_high = None
                st.after_low = None

    def _reset_day(self) -> None:
        """New trading day: clear all day-level + per-session accumulators,
        carry yesterday's RTH close into prev_close, then re-anchor from the
        fresh snapshot. Day metrics are NEVER reset on an intra-day session
        change — only here, once per day (closed → active)."""
        with self._lock:
            for st in self._states.values():
                st.prev_close = st.rth_close if st.rth_close is not None else None
                st.rth_close = None
                st.day_open = None
                st.day_high = None
                st.day_low = None
                st.day_volume = 0.0
                st.after_volume = 0.0
                st.after_high = None
                st.after_low = None
                st.pre_volume = 0.0
                st.pre_high = None
                st.last_price = None
            self._top_cache.clear()
        try:
            self._refresh_from_snapshot()
        except Exception as e:  # noqa: BLE001
            logger.warning("[LIVE] day reset snapshot refresh failed: %s", e)

    async def _allowlist_refresh_loop(self) -> None:
        """Rebuild the CS+ADRC allow-list once a day at ~4:00 AM ET (pre-market).
        A failed refresh keeps the previous list (see _refresh_allowlist)."""
        while not self._stop:
            try:
                await asyncio.sleep(_seconds_until_et(ALLOWLIST_REFRESH_ET))
                if self._stop:
                    break
                await asyncio.to_thread(self._refresh_allowlist)
            except asyncio.CancelledError:  # pragma: no cover
                break
            except Exception as e:  # noqa: BLE001
                logger.debug("[LIVE] allow-list refresh loop error: %s", e)
                await asyncio.sleep(3600)

    # ── Massive WebSocket consumer ───────────────────────────────────────────
    async def _consume_massive_ws(self) -> None:
        if websockets is None or not API_KEY:
            logger.warning("[LIVE] WS consumer disabled (no websockets lib or API key); REST fallback only")
            return
        # Build an SSL context backed by certifi's CA bundle. The stdlib default
        # context fails on macOS Python ("CERTIFICATE_VERIFY_FAILED"); httpx works
        # because it bundles certifi, so we mirror that here for the WS client.
        ssl_ctx = None
        if WS_URL.startswith("wss"):
            try:
                import certifi
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            except Exception:  # noqa: BLE001
                ssl_ctx = ssl.create_default_context()
        backoff = 1.0
        while not self._stop:
            connected_at: Optional[float] = None
            try:
                async with websockets.connect(WS_URL, ssl=ssl_ctx, ping_interval=20, max_size=2**21) as ws:
                    await ws.send(json.dumps({"action": "auth", "params": API_KEY}))
                    # Second aggregates for the whole US market; filtered server-side.
                    await ws.send(json.dumps({"action": "subscribe", "params": "A.*"}))
                    self._ws_connected = True
                    connected_at = time.monotonic()
                    logger.info("[LIVE] Massive WS connected, subscribed A.*")
                    async for raw in ws:
                        self._handle_ws_message(raw)
            except asyncio.CancelledError:  # pragma: no cover
                break
            except Exception as e:  # noqa: BLE001
                self._ws_connected = False
                # Reset only after a connection that stayed up; resetting on
                # every connect turns a 1008 kick-loop (another consumer on the
                # same API key) into a 1s hammer on the socket and the logs.
                if connected_at is not None and time.monotonic() - connected_at >= 60.0:
                    backoff = 1.0
                logger.warning("[LIVE] WS disconnected (%s); reconnecting in %.0fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
        self._ws_connected = False

    def _handle_ws_message(self, raw: Any) -> None:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return
        events = data if isinstance(data, list) else [data]
        for ev in events:
            if not isinstance(ev, dict):
                continue
            etype = ev.get("ev")
            if etype in ("A", "AM"):
                self._apply_aggregate(ev)
            # ignore status / other events

    def _apply_aggregate(self, ev: Dict[str, Any]) -> None:
        sym = str(ev.get("sym", ""))
        if not sym:
            return
        if self._session == "closed":
            return
        ts_raw = ev.get("s") or ev.get("e") or ev.get("t")
        in_after = _ts_in_after(ts_raw) if ts_raw is not None else (self._session == "after")
        in_pre = _ts_in_pre(ts_raw) if ts_raw is not None else (self._session == "pre")
        with self._lock:
            if sym not in self._allowlist:
                # Defensive allow-list gate (PRD §05.3): only CS + ADRC pass.
                return
            st = self._states.get(sym)
            if st is None:
                st = TickerLiveState(ticker=sym)
                self._states[sym] = st
            price = _f(ev.get("c")) or _f(ev.get("vw")) or st.last_price
            if price is not None:
                st.last_price = price
            # Day-level high/low (max/min across the whole trading day).
            hi, lo = _f(ev.get("h")), _f(ev.get("l"))
            if hi is not None:
                st.day_high = hi if st.day_high is None else max(st.day_high, hi)
            if lo is not None:
                st.day_low = lo if st.day_low is None else min(st.day_low, lo)
            # Day volume: Polygon's second-aggregate carries the accumulated daily
            # volume in `av` (NOT `a`, which is an avg price). Fall back to summing
            # the per-bar `v`.
            av = _f(ev.get("av"))
            v = _f(ev.get("v"))
            if av is not None:
                st.day_volume = av
            elif v is not None:
                st.day_volume += v
            # Capture the RTH open the first time we see a bar inside regular hours.
            if st.day_open is None and ts_raw is not None and _ts_in_rth(ts_raw):
                st.day_open = _f(ev.get("o")) or price
            # Per-session accumulators: only the window this bar belongs to, so the
            # Premarket/Aftermarket tabs reflect what is moving NOW.
            if in_after and v is not None:
                st.after_volume += v
                if hi is not None:
                    st.after_high = hi if st.after_high is None else max(st.after_high, hi)
                if lo is not None:
                    st.after_low = lo if st.after_low is None else min(st.after_low, lo)
            elif in_pre and v is not None:
                st.pre_volume += v
                if hi is not None:
                    st.pre_high = hi if st.pre_high is None else max(st.pre_high, hi)
            st.updated_at = time.time()

    # ── leaderboard ──────────────────────────────────────────────────────────
    def _metrics(self, st: TickerLiveState) -> Optional[Dict[str, Any]]:
        prev = st.prev_close
        price = st.last_price
        if not prev or prev <= 0 or price is None:
            return None
        day_change_pct = (price / prev - 1.0) * 100.0
        day_high = st.day_high if st.day_high is not None else price
        gap_pct = ((st.day_open / prev - 1.0) * 100.0) if st.day_open else 0.0
        return_pct = ((price / st.day_open - 1.0) * 100.0) if st.day_open else 0.0
        # Aftermarket move measured from the frozen RTH close (day.c). None when
        # rth_close is unknown (e.g. backend booted inside after-hours) so the
        # Aftermarket tab drops it instead of falling back to the day change.
        after_pct = ((price / st.rth_close - 1.0) * 100.0) if st.rth_close and st.rth_close > 0 else None
        pre_pct = ((st.pre_high / prev - 1.0) * 100.0) if st.pre_high else None
        avg_vol = st.avg_vol_20d
        rvol = (st.day_volume / avg_vol) if (avg_vol and avg_vol > 0) else 1.0
        return {
            "ticker": st.ticker,
            "name": st.name,
            "price": round(price, 4),
            "prev_close": round(prev, 4),
            "day_change_pct": round(day_change_pct, 2),
            "change_pct": round(day_change_pct, 2),   # alias kept for the current frontend
            "gap_pct": round(gap_pct, 2),
            "return_pct": round(return_pct, 2),
            "after_pct": round(after_pct, 2) if after_pct is not None else None,
            "after_volume": round(st.after_volume, 0) if st.after_volume else None,
            "after_high": round(st.after_high, 4) if st.after_high is not None else None,
            "pre_pct": round(pre_pct, 2) if pre_pct is not None else None,
            "pre_volume": round(st.pre_volume, 0) if st.pre_volume else None,
            "pre_high": round(st.pre_high, 4) if st.pre_high is not None else None,
            "volume": round(st.day_volume, 0),        # day volume (alias for the frontend)
            "day_volume": round(st.day_volume, 0),
            "high": round(day_high, 4),
            "low": round(st.day_low, 4) if st.day_low is not None else None,
            "rvol": round(rvol, 2),
        }

    def get_top(self, tab: str, limit: int = TOP_N) -> List[Dict[str, Any]]:
        """Top movers for a tab. Cached for up to TOP_CACHE_TTL to avoid
        recomputing per connected client."""
        if tab not in VALID_TABS:
            return []
        cached = self._top_cache.get(tab)
        now = time.time()
        if cached and (now - cached[0]) < TOP_CACHE_TTL:
            return cached[1]

        with self._lock:
            states = list(self._states.values())

        rows: List[Dict[str, Any]] = []
        for st in states:
            m = self._metrics(st)            # no volume gate: rank purely by the tab metric
            if m is None:
                continue
            chg = m["change_pct"]
            if tab == TAB_LOSERS:
                if chg < 0:                  # any decline ranks as a loser
                    rows.append(m)
            elif tab == TAB_GAINERS:
                if chg > 0:                  # any advance ranks as a gainer
                    rows.append(m)
            elif tab == TAB_PRE:
                # Premarket ranks by the pre-market peak; needs the pre datum.
                if m.get("pre_pct") is not None:
                    rows.append(m)
            elif tab == TAB_AFT:
                # Aftermarket ranks by the after-hours move from the RTH close;
                # needs rth_close (otherwise there is no after datum to rank on).
                if m.get("after_pct") is not None:
                    rows.append(m)

        # Sort by the metric that defines each tab; losers ascending (biggest drop first).
        if tab == TAB_LOSERS:
            rows.sort(key=lambda r: r["change_pct"])
        elif tab == TAB_PRE:
            rows.sort(key=lambda r: (r.get("pre_pct") if r.get("pre_pct") is not None else r["change_pct"]), reverse=True)
        elif tab == TAB_AFT:
            rows.sort(key=lambda r: (r.get("after_pct") if r.get("after_pct") is not None else 0.0), reverse=True)
        else:  # TAB_GAINERS
            rows.sort(key=lambda r: r["change_pct"], reverse=True)
        rows = rows[:limit]
        self._top_cache[tab] = (now, rows)
        return rows


def _seconds_until_et(target: dtime) -> float:
    """Seconds from now until the next occurrence of `target` time in ET."""
    now = datetime.now(ET)
    nxt = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return max(60.0, (nxt - now).total_seconds())


def _ts_window(ts_ms: Any) -> Optional[str]:
    """Return the market window ('pre' | 'rth' | 'after') for a Unix-ms
    timestamp (ET), or None if it falls outside all sessions / is unparseable."""
    f = _f(ts_ms)
    if f is None:
        return None
    try:
        dt = datetime.fromtimestamp(f / 1000.0, ET)
    except (OverflowError, OSError, ValueError):
        return None
    t = dt.timetz().replace(tzinfo=None)
    if PRE_OPEN <= t < RTH_OPEN:
        return "pre"
    if RTH_OPEN <= t < RTH_CLOSE:
        return "rth"
    if RTH_CLOSE <= t < AFT_CLOSE:
        return "after"
    return None


def _ts_in_rth(ts_ms: Any) -> bool:
    """True if a Unix-ms timestamp falls inside US regular trading hours."""
    return _ts_window(ts_ms) == "rth"


def _ts_in_pre(ts_ms: Any) -> bool:
    """True if a Unix-ms timestamp falls inside the pre-market window (04:00–09:30 ET)."""
    return _ts_window(ts_ms) == "pre"


def _ts_in_after(ts_ms: Any) -> bool:
    """True if a Unix-ms timestamp falls inside the after-hours window (16:00–20:00 ET)."""
    return _ts_window(ts_ms) == "after"


# Module-level singleton used by the router + lifespan.
live_screener_service = LiveScreenerService()
