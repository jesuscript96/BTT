"""
Live screener service — real-time US stock screener fed by Massive's WebSocket.

Responsibilities (all in-process, no DB writes on the hot path):
  * Bootstrap a per-ticker state map from the REST snapshot (prev_close, last
    price, session volume) + an avg-20d-volume lookup from DuckDB (for RVol) +
    the US equities universe from `massive.tickers`.
  * Keep that state fresh by consuming Massive's second-aggregate stream
    (`A.*`) over `wss://socket.massive.com`. Each message is O(1): update last
    price, session high/low, accumulated volume and the RTH open.
  * On demand, `get_top(tab)` applies the official trading formulas (§3.2 of the
    PRD), filters (US + volume >= 50k + change >= ±15%) and returns the top 50.

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
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional
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

MIN_VOLUME = 50_000          # session volume floor to qualify
MIN_CHANGE_PCT = 15.0        # explosive-move threshold (gainers / pre / after)
TOP_N = 50                   # rows streamed per tab
SNAPSHOT_POLL_SECONDS = 20   # REST fallback cadence while WS is down / market closed
TOP_CACHE_TTL = 1.0          # recompute a tab's leaderboard at most once per second

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
    prev_close: Optional[float] = None
    avg_vol_20d: Optional[float] = None
    last_price: Optional[float] = None
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    session_volume: float = 0.0
    rth_open: Optional[float] = None
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
        self._lock = threading.RLock()
        self._ws_connected = False
        self._bootstrapped = False
        self._stop = False
        self._top_cache: Dict[str, tuple] = {}  # tab -> (ts, rows)
        self._tasks: List[asyncio.Task] = []

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def start(self) -> None:
        """Warm the critical state fast (universe + REST snapshot) so the grid
        has data immediately, then launch the WS consumer + poller. The avg-20d
        volume table (RVol only, non-critical) loads in the background so a slow
        or contended DuckDB query can never delay the live stream."""
        await asyncio.to_thread(self._load_universe)
        try:
            await asyncio.to_thread(self._refresh_from_snapshot)
        except Exception as e:  # noqa: BLE001
            logger.warning("[LIVE] initial snapshot failed: %s", e)
        self._bootstrapped = True
        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._consume_massive_ws()),
            loop.create_task(self._poll_snapshot_loop()),
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

    # ── bootstrap ────────────────────────────────────────────────────────────
    def _load_universe(self) -> None:
        try:
            from app.services.cache_service import get_tickers_df

            df = get_tickers_df()
            with self._lock:
                for row in df.itertuples(index=False):
                    tk = str(getattr(row, "ticker", "") or "").upper()
                    if not tk:
                        continue
                    self._states[tk] = TickerLiveState(
                        ticker=tk,
                        name=str(getattr(row, "name", "") or tk),
                        exchange=str(getattr(row, "primary_exchange", "") or ""),
                    )
            logger.info("[LIVE] universe loaded: %d tickers", len(self._states))
        except Exception as e:  # noqa: BLE001
            logger.warning("[LIVE] universe load failed (%s); will rely on snapshot", e)

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
                    st = self._states.get(str(tk).upper())
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
                sym = str(t.get("ticker", "")).upper()
                if not sym:
                    continue
                st = self._states.get(sym)
                if st is None:
                    st = TickerLiveState(ticker=sym)
                    self._states[sym] = st
                day = t.get("day") or {}
                prev = t.get("prevDay") or {}
                last = t.get("lastTrade") or {}
                mn = t.get("min") or {}
                st.prev_close = _f(prev.get("c")) or st.prev_close
                st.last_price = _f(last.get("p")) or _f(mn.get("c")) or _f(day.get("c")) or st.last_price
                st.session_volume = _f(day.get("v")) or st.session_volume or 0.0
                st.session_high = _f(day.get("h")) or st.session_high
                st.session_low = _f(day.get("l")) or st.session_low
                if st.rth_open is None:
                    st.rth_open = _f(day.get("o"))
                st.updated_at = time.time()
                updated += 1
        logger.info("[LIVE] snapshot refresh applied to %d tickers", updated)

    async def _poll_snapshot_loop(self) -> None:
        """Keep the map warm via REST while the WS is down or the market is
        closed. Cheap and bounded; skips work when the WS is actively feeding."""
        while not self._stop:
            try:
                await asyncio.sleep(SNAPSHOT_POLL_SECONDS)
                if self._ws_connected and current_session() != "closed":
                    continue  # WS is the source of truth during live sessions
                await asyncio.to_thread(self._refresh_from_snapshot)
            except asyncio.CancelledError:  # pragma: no cover
                break
            except Exception as e:  # noqa: BLE001
                logger.debug("[LIVE] snapshot poll error: %s", e)

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
            conn_start = None
            try:
                async with websockets.connect(WS_URL, ssl=ssl_ctx, ping_interval=20, max_size=2**21) as ws:
                    await ws.send(json.dumps({"action": "auth", "params": API_KEY}))
                    # Second aggregates for the whole US market; filtered server-side.
                    await ws.send(json.dumps({"action": "subscribe", "params": "A.*"}))
                    self._ws_connected = True
                    conn_start = time.monotonic()
                    logger.info("[LIVE] Massive WS connected, subscribed A.*")
                    async for raw in ws:
                        self._handle_ws_message(raw)
            except asyncio.CancelledError:  # pragma: no cover
                break
            except Exception as e:  # noqa: BLE001
                self._ws_connected = False
                # Backoff CRECIENTE cuando nos echan al instante (p.ej. 1008
                # max-connections porque otra instancia usa la misma API key): antes
                # se reseteaba backoff=1.0 en cada connect, pero como el kick llega
                # justo tras conectar, reconectaba cada 1s → tormenta de handshakes
                # SSL nativos que (a) spamea logs y (b) sube la probabilidad del
                # segfault de fork en los backtests paralelos. Solo se resetea a 1s si
                # la conexión fue ESTABLE (>15s) = caída legítima que sí merece agilidad.
                stable = conn_start is not None and (time.monotonic() - conn_start) > 15.0
                if stable:
                    backoff = 1.0
                logger.warning("[LIVE] WS disconnected (%s); reconnecting in %.0fs", e, backoff)
                await asyncio.sleep(backoff)
                if not stable:
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
        sym = str(ev.get("sym", "")).upper()
        if not sym:
            return
        with self._lock:
            st = self._states.get(sym)
            if st is None:
                # Unknown symbol (not in our equities universe) — skip to stay light.
                return
            price = _f(ev.get("c")) or _f(ev.get("vw")) or st.last_price
            if price is not None:
                st.last_price = price
            hi, lo = _f(ev.get("h")), _f(ev.get("l"))
            if hi is not None:
                st.session_high = hi if st.session_high is None else max(st.session_high, hi)
            if lo is not None:
                st.session_low = lo if st.session_low is None else min(st.session_low, lo)
            acc = _f(ev.get("a"))  # accumulated daily volume (Polygon-style)
            if acc is not None:
                st.session_volume = acc
            else:
                v = _f(ev.get("v"))
                if v is not None:
                    st.session_volume += v
            # Capture the RTH open the first time we see a bar inside regular hours.
            if st.rth_open is None:
                ts = ev.get("s") or ev.get("e") or ev.get("t")
                if ts is not None and _ts_in_rth(ts):
                    st.rth_open = _f(ev.get("o")) or price
            st.updated_at = time.time()

    # ── leaderboard ──────────────────────────────────────────────────────────
    def _metrics(self, st: TickerLiveState) -> Optional[Dict[str, Any]]:
        prev = st.prev_close
        price = st.last_price
        if not prev or prev <= 0 or price is None:
            return None
        change_pct = (price / prev - 1.0) * 100.0
        session_high = st.session_high if st.session_high is not None else price
        pmh_gap_pct = (session_high / prev - 1.0) * 100.0
        gap_pct = ((st.rth_open / prev - 1.0) * 100.0) if st.rth_open else 0.0
        return_pct = ((price / st.rth_open - 1.0) * 100.0) if st.rth_open else 0.0
        avg_vol = st.avg_vol_20d
        rvol = (st.session_volume / avg_vol) if (avg_vol and avg_vol > 0) else 1.0
        return {
            "ticker": st.ticker,
            "name": st.name,
            "price": round(price, 4),
            "prev_close": round(prev, 4),
            "change_pct": round(change_pct, 2),
            "pmh_gap_pct": round(pmh_gap_pct, 2),
            "amh_gap_pct": round(pmh_gap_pct, 2),  # same session-high gap, shown in AM tab
            "gap_pct": round(gap_pct, 2),
            "return_pct": round(return_pct, 2),
            "volume": round(st.session_volume, 0),
            "high": round(session_high, 4),
            "low": round(st.session_low, 4) if st.session_low is not None else None,
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
            if st.session_volume < MIN_VOLUME:
                continue
            m = self._metrics(st)
            if m is None:
                continue
            if tab == TAB_LOSERS:
                if m["change_pct"] <= -MIN_CHANGE_PCT:
                    rows.append(m)
            elif tab == TAB_GAINERS:
                if m["change_pct"] >= MIN_CHANGE_PCT:
                    rows.append(m)
            elif tab == TAB_PRE:
                if m["change_pct"] >= MIN_CHANGE_PCT or m["pmh_gap_pct"] >= MIN_CHANGE_PCT:
                    rows.append(m)
            elif tab == TAB_AFT:
                if m["change_pct"] >= MIN_CHANGE_PCT or m["amh_gap_pct"] >= MIN_CHANGE_PCT:
                    rows.append(m)

        reverse = tab != TAB_LOSERS
        rows.sort(key=lambda r: r["change_pct"], reverse=reverse)
        rows = rows[:limit]
        self._top_cache[tab] = (now, rows)
        return rows


def _ts_in_rth(ts_ms: Any) -> bool:
    """True if a Unix-ms timestamp falls inside US regular trading hours."""
    f = _f(ts_ms)
    if f is None:
        return False
    try:
        dt = datetime.fromtimestamp(f / 1000.0, ET)
    except (OverflowError, OSError, ValueError):
        return False
    t = dt.timetz().replace(tzinfo=None)
    return RTH_OPEN <= t < RTH_CLOSE


# Module-level singleton used by the router + lifespan.
live_screener_service = LiveScreenerService()
