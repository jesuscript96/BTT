from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from app.database import get_db_connection
import asyncio
import logging
import math
import threading
import time
from datetime import datetime, timedelta

from app.services.live_screener_service import (
    live_screener_service,
    VALID_TABS,
    TAB_GAINERS,
)

logger = logging.getLogger("btt.screener")

router = APIRouter(
    prefix="/api/screener",
    tags=["Screener"]
)

def _safe_float(v):
    if v is None:
        return 0.0
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return 0.0
        return fv
    except (TypeError, ValueError):
        return 0.0

# ── In-memory cache ──────────────────────────────────────────
_screener_cache = {}
_screener_cache_lock = threading.Lock()
SCREENER_CACHE_TTL = timedelta(minutes=5)


@router.get("/daily")
def get_screener_daily(limit: int = 100):
    """
    Return top gainers and top losers from the latest available trading day
    in daily_metrics.  Premarket and aftermarket tabs are reserved for future
    real-time integration and return empty lists for now.
    """
    now = datetime.now()

    # Check cache
    with _screener_cache_lock:
        if "daily" in _screener_cache:
            cached_data, expiry = _screener_cache["daily"]
            if now < expiry:
                return cached_data

    con = None
    try:
        con = get_db_connection(read_only=True)

        # 1. Find the latest trading date using fast MAX(timestamp) without CAST
        latest_row = con.execute(
            "SELECT MAX(timestamp) FROM daily_metrics"
        ).fetchone()
        if not latest_row or not latest_row[0]:
            return {
                "date": None,
                "gainers": [],
                "losers": [],
                "premarket": [],
                "aftermarket": [],
            }

        latest_dt = latest_row[0]
        latest_date = latest_dt.date()

        # 2. Find the previous trading date
        prev_row = con.execute(
            "SELECT MAX(timestamp) FROM daily_metrics WHERE timestamp < ?",
            [latest_dt]
        ).fetchone()
        prev_date = prev_row[0].date() if (prev_row and prev_row[0]) else None

        # 3. Fetch all records for latest_date with partition pruning and self-join for prev_volume
        if prev_date:
            query = """
                SELECT
                    today.ticker,
                    today.rth_close AS price,
                    today.day_return_pct,
                    today.rth_run_pct,
                    today.gap_pct,
                    today.rth_volume AS volume,
                    today.prev_close,
                    today.rth_open AS open,
                    today.rth_high AS high,
                    today.rth_low AS low,
                    today.rth_range_pct AS range_pct,
                    yesterday.rth_volume AS prev_volume,
                    COALESCE(t.name, today.ticker) AS name
                FROM daily_metrics today
                LEFT JOIN daily_metrics yesterday ON today.ticker = yesterday.ticker
                    AND yesterday.year = ?
                    AND yesterday.month = ?
                    AND CAST(yesterday.timestamp AS DATE) = ?
                LEFT JOIN tickers t ON today.ticker = t.ticker
                WHERE today.year = ?
                  AND today.month = ?
                  AND CAST(today.timestamp AS DATE) = ?
                  AND today.rth_close IS NOT NULL
                  AND today.rth_close > 0
            """
            params = [
                prev_date.year, prev_date.month, prev_date,
                latest_date.year, latest_date.month, latest_date
            ]
        else:
            query = """
                SELECT
                    today.ticker,
                    today.rth_close AS price,
                    today.day_return_pct,
                    today.rth_run_pct,
                    today.gap_pct,
                    today.rth_volume AS volume,
                    today.prev_close,
                    today.rth_open AS open,
                    today.rth_high AS high,
                    today.rth_low AS low,
                    today.rth_range_pct AS range_pct,
                    CAST(NULL AS DOUBLE) AS prev_volume,
                    COALESCE(t.name, today.ticker) AS name
                FROM daily_metrics today
                LEFT JOIN tickers t ON today.ticker = t.ticker
                WHERE today.year = ?
                  AND today.month = ?
                  AND CAST(today.timestamp AS DATE) = ?
                  AND today.rth_close IS NOT NULL
                  AND today.rth_close > 0
            """
            params = [
                latest_date.year, latest_date.month, latest_date
            ]

        cur = con.execute(query, params)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()

        # Build records
        all_records = []
        for r in rows:
            rd = dict(zip(cols, r))
            all_records.append({
                "ticker": rd.get("ticker", ""),
                "name": rd.get("name", rd.get("ticker", "")),
                "price": _safe_float(rd.get("price")),
                "change_pct": _safe_float(rd.get("day_return_pct")),
                "return_pct": _safe_float(rd.get("rth_run_pct")),
                "gap_pct": _safe_float(rd.get("gap_pct")),
                "volume": _safe_float(rd.get("volume")),
                "prev_close": _safe_float(rd.get("prev_close")),
                "open": _safe_float(rd.get("open")),
                "high": _safe_float(rd.get("high")),
                "low": _safe_float(rd.get("low")),
                "prev_volume": _safe_float(rd.get("prev_volume")),
                "high_spike_pct": 0.0,
                "low_spike_pct": 0.0,
                "range_pct": _safe_float(rd.get("range_pct")),
            })

        # 3. Sort into categories
        # Top Gainers: positive day_return_pct, sorted DESC
        gainers = sorted(
            [r for r in all_records if r["change_pct"] > 0],
            key=lambda x: x["change_pct"],
            reverse=True,
        )[:limit]

        # Top Losers: negative day_return_pct, sorted ASC (most negative first)
        losers = sorted(
            [r for r in all_records if r["change_pct"] < 0],
            key=lambda x: x["change_pct"],
        )[:limit]

        result = {
            "date": str(latest_date),
            "total_records": len(all_records),
            "gainers": gainers,
            "losers": losers,
            "premarket": [],   # Reserved for future real-time data
            "aftermarket": [], # Reserved for future real-time data
        }

        # Cache result
        with _screener_cache_lock:
            _screener_cache["daily"] = (result, now + SCREENER_CACHE_TTL)

        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con:
            con.close()


# ─── Live screener WebSocket ─────────────────────────────────────────────────
# Internal app backend only — deliberately NOT exposed through the commercial
# public API (api_public). The page itself is Admin-gated (LockedFeature).
@router.websocket("/live")
async def screener_live(websocket: WebSocket):
    """Stream the top movers for the subscribed tab once per second.

    Client → server: {"action": "subscribe", "tab": "RTH Gainers"}
    Server → client: {"tab", "timestamp", "session", "ws_connected", "records": [...]}
    """
    await websocket.accept()
    state = {"tab": TAB_GAINERS}
    tab_changed = asyncio.Event()

    async def receiver():
        # Listen for tab switches; on any error, unblock the sender so it can
        # notice the disconnect and tear down cleanly.
        try:
            while True:
                msg = await websocket.receive_json()
                if isinstance(msg, dict) and msg.get("action") == "subscribe":
                    tab = msg.get("tab")
                    if tab in VALID_TABS:
                        state["tab"] = tab
                        tab_changed.set()
        except Exception:
            tab_changed.set()

    recv_task = asyncio.create_task(receiver())
    try:
        while True:
            tab = state["tab"]
            await websocket.send_json({
                "tab": tab,
                "timestamp": int(time.time()),
                "session": live_screener_service.session,
                "ws_connected": live_screener_service.ws_connected,
                "records": live_screener_service.get_top(tab),
            })
            # Re-emit every second, or immediately when the client switches tab.
            try:
                await asyncio.wait_for(tab_changed.wait(), timeout=1.0)
                tab_changed.clear()
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        logger.debug("[LIVE] ws client error: %s", e)
    finally:
        recv_task.cancel()
