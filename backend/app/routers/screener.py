from fastapi import APIRouter, HTTPException
from app.database import get_db_connection
import math
import threading
from datetime import datetime, timedelta

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
