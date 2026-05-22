from fastapi import APIRouter, HTTPException, Request
from datetime import date
from typing import Optional
from app.database import get_db_connection
import math
import json

def safe_float(v):
    if v is None: return 0.0
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv): return 0.0
        return fv
    except:
        return 0.0

router = APIRouter(
    prefix="/api/market",
    tags=["market"]
)

from app.services.query_service import build_screener_query, get_stats_sql_logic, map_stats_row
from app.services.cache_service import get_hot_daily_df
import pandas as pd

@router.get("/screener")
def screen_market(
    request: Request,
    min_gap: float = 0.0, max_gap: Optional[float] = None,
    min_gap_at_open_pct: float = 0.0,
    min_run: float = 0.0, min_volume: float = 0.0,
    trade_date: Optional[date] = None, start_date: Optional[date] = None,
    end_date: Optional[date] = None, ticker: Optional[str] = None,
    limit: int = 5000
):
    con = None
    try:
        # ── Hot Cache Fast Path ──
        hot_df = get_hot_daily_df()
        effective_gap = max(min_gap, min_gap_at_open_pct)
        if hot_df is not None and effective_gap >= 10.0:
            result = hot_df.copy()
            if effective_gap:
                result = result[result['gap_pct'] >= effective_gap]
            if max_gap is not None:
                result = result[result['gap_pct'] <= max_gap]
            if start_date:
                result = result[result['timestamp'] >= pd.Timestamp(str(start_date))]
            if end_date:
                result = result[result['timestamp'] <= pd.Timestamp(str(end_date))]
            if min_volume:
                result = result[result['volume'] >= min_volume]
            if ticker:
                result = result[result['ticker'] == ticker.upper()]

            # Compute stats from full filtered result (before head)
            import numpy as np
            col_map = {
                'gap_pct': 'gap_at_open_pct',
                'rth_run_pct': 'rth_run_pct',
                'day_return_pct': 'day_return_pct',
                'pm_volume': 'avg_pm_volume',
                'volume': 'avg_volume',
                'pmh_gap_pct': 'pm_high_gap_pct',
                'pmh_fade_pct': 'pmh_fade_to_open_pct',
                'rth_fade_pct': 'rth_fade_to_close_pct',
                'close_red': 'close_red_pct',
                'high_spike_pct': 'high_spike_pct',
                'low_spike_pct': 'low_spike_pct',
                'rth_range_pct': 'rth_range_pct',
            }
            stats_payload = {
                "count": len(result),
                "avg": {}, "p25": {}, "p50": {}, "p75": {},
                "distributions": {"hod_time": {}, "lod_time": {}}
            }
            for raw_col, frontend_key in col_map.items():
                if raw_col not in result.columns:
                    continue
                series = result[raw_col].dropna().astype(float)
                if len(series) > 0:
                    stats_payload["avg"][frontend_key] = float(series.mean())
                    stats_payload["p25"][frontend_key] = float(series.quantile(0.25))
                    stats_payload["p50"][frontend_key] = float(series.quantile(0.50))
                    stats_payload["p75"][frontend_key] = float(series.quantile(0.75))

            result = result.sort_values(['timestamp', 'gap_pct'], ascending=[False, False]).head(limit)

            recs = []
            for _, rd in result.iterrows():
                recs.append({
                    "ticker": rd['ticker'],
                    "date": str(rd['timestamp']),
                    "open": safe_float(rd['open']), "high": safe_float(rd['high']), "low": safe_float(rd['low']), "close": safe_float(rd['close']),
                    "volume": safe_float(rd['volume']),
                    "gap_at_open_pct": safe_float(rd['gap_pct']),
                    "rth_run_pct": safe_float(rd.get('rth_run_pct', 0)),
                    "day_return_pct": safe_float(rd.get('day_return_pct', 0)),
                    "pmh_gap_pct": safe_float(rd.get('pmh_gap_pct', 0)),
                    "pmh_fade_pct": safe_float(rd.get('pmh_fade_pct', 0)),
                    "rth_fade_pct": safe_float(rd.get('rth_fade_pct', 0)),
                })
            return {
                "records": recs,
                "stats": stats_payload,
                "source": "hot_cache"
            }

        # ── Normal GCS Path ──
        con = get_db_connection(read_only=True)
        # Prepare filters dictionary for service
        filters = dict(request.query_params)
        filters.update({
            'min_gap': min_gap, 'max_gap': max_gap,
            'min_run': min_run, 'min_volume': min_volume,
            'trade_date': trade_date, 'start_date': start_date,
            'end_date': end_date, 'ticker': ticker
        })

        # Use shared query service
        rec_query, sql_p, where_d, where_i, where_m, where_base = build_screener_query(filters, limit)

        # Execute
        cur = con.execute(rec_query, sql_p)
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        
        recs = []
        for r in rows:
            rd = dict(zip(cols, r))
            
            # Helper to get valid float/date safely
            def get_f(k): return safe_float(rd.get(k, 0))
            
            # MAPPING: Use actual schema names from daily_metrics
            recs.append({
                "ticker": rd.get('ticker', 'UNKNOWN'),
                "date": str(rd.get('date', rd.get('timestamp', ''))),
                "open": get_f('open'), "high": get_f('high'), "low": get_f('low'), "close": get_f('close'), 
                "volume": get_f('volume'),
                
                # New Schema Names mapping to Frontend keys
                "gap_at_open_pct": get_f('gap_pct'),
                "rth_run_pct": get_f('rth_run_pct'),
                "day_return_pct": get_f('day_return_pct'), 
                "pmh_gap_pct": get_f('pmh_gap_pct'),
                "pmh_fade_pct": get_f('pmh_fade_pct'), 
                "rth_fade_pct": get_f('rth_fade_pct')
            })
        
        st_query = get_stats_sql_logic(where_d, where_i, where_m, where_base)
        st_rows = con.execute(st_query, sql_p).fetchall()
        
        stats_payload = {"count": len(recs), "avg": {}, "p25": {}, "p50": {}, "p75": {}, "distributions": {"hod_time": {}, "lod_time": {}}}
        if st_rows:
            for s_row in st_rows:
                s_key = s_row[0]
                if s_key == 'avg':
                    stats_payload['avg'] = map_stats_row(s_row)
                    # distribution mocks
                    stats_payload['distributions'] = {"hod_time": {}, "lod_time": {}}
                elif s_key in ['p25', 'p50', 'p75']:
                    stats_payload[s_key] = map_stats_row(s_row)

        return {"records": recs, "stats": stats_payload}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/ticker/{ticker}/intraday")
def get_intraday_data(ticker: str, trade_date: Optional[date] = None):
    con = None
    try:
        con = get_db_connection(read_only=True)
        if not trade_date:
            latest = con.execute("SELECT MAX(date) FROM intraday_1m WHERE ticker = ?", [ticker]).fetchone()
            if latest and latest[0]: trade_date = latest[0]
            else: return []

        query = """
            SELECT timestamp, open, high, low, close, volume
            FROM intraday_1m WHERE ticker = ? AND date = ?
            GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY timestamp ASC
        """
        cur = con.execute(query, [ticker, trade_date])
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        recs = []
        for r in rows:
            rd = dict(zip(cols, r))
            recs.append({
                "timestamp": str(rd['timestamp']),
                "open": safe_float(rd['open']), "high": safe_float(rd['high']), "low": safe_float(rd['low']),
                "close": safe_float(rd['close']), "volume": safe_float(rd['volume'])
            })
        return recs
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/ticker/{ticker}/metrics_history")
def get_metrics_history(ticker: str, limit: int = 500):
    con = None
    try:
        con = get_db_connection(read_only=True)
        # Using simple query fallback
        query = "SELECT * FROM daily_metrics WHERE ticker = ? ORDER BY timestamp DESC LIMIT ?"
        cur = con.execute(query, [ticker, limit])
        cols, rows = [d[0] for d in cur.description], cur.fetchall()
        
        data = []
        for r in rows:
            rd = dict(zip(cols, r))
            data.append({
                "date": str(rd.get('date', rd.get('timestamp', ''))),
                "rth_range_pct": safe_float(rd.get('rth_range_pct', 0)),
                "return_close_vs_open_pct": safe_float(rd.get('day_return_pct', 0)),
                "high_spike_pct": safe_float(rd.get('high_spike_pct', 0)),
                "gap_extension_pct": 0.0, # Not in schema yet?
                "pmh_gap_pct": safe_float(rd.get('pmh_gap_pct', 0)),
                "pm_fade_at_open_pct": safe_float(rd.get('pmh_fade_pct', 0))
            })
        return data[::-1]
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/latest-date")
def get_latest_market_date():
    con = None
    try:
        con = get_db_connection(read_only=True)
        latest = con.execute("SELECT MAX(CAST(timestamp AS VARCHAR)[:10]) FROM daily_metrics").fetchone()
        return {"date": str(latest[0])} if latest and latest[0] else {"date": None}
    finally:
        if con: con.close()

@router.get("/aggregate/intraday")
def get_aggregate_intraday(
    request: Request,
    min_gap: float = 0.0, max_gap: Optional[float] = None,
    min_gap_at_open_pct: float = 0.0,
    min_run: float = 0.0, min_volume: float = 0.0,
    trade_date: Optional[date] = None, start_date: Optional[date] = None,
    end_date: Optional[date] = None, ticker: Optional[str] = None
):
    con = None
    try:
        filters = dict(request.query_params)
        filters.update({
            'min_gap': min_gap, 'max_gap': max_gap,
            'min_run': min_run, 'min_volume': min_volume,
            'trade_date': trade_date, 'start_date': start_date,
            'end_date': end_date, 'ticker': ticker
        })

        # ── Hot Cache Fast Path ──
        from app.services.cache_service import get_hot_daily_df
        hot_df = get_hot_daily_df()
        effective_gap = max(min_gap, min_gap_at_open_pct)

        if hot_df is not None and effective_gap >= 10.0:
            result_df = hot_df.copy()
            if effective_gap:
                result_df = result_df[result_df['gap_pct'] >= effective_gap]
            if max_gap:
                result_df = result_df[result_df['gap_pct'] <= max_gap]
            if start_date:
                result_df = result_df[result_df['timestamp'] >= pd.Timestamp(str(start_date))]
            if end_date:
                result_df = result_df[result_df['timestamp'] <= pd.Timestamp(str(end_date))]

            result_df = result_df.sort_values(['timestamp', 'gap_pct'], ascending=[False, False])

            if result_df.empty:
                return []

            target_date = pd.Timestamp(result_df.iloc[0]['timestamp']).date()
            tickers = result_df[result_df['timestamp'].dt.date == target_date]['ticker'].unique().tolist()[:50]

            if not tickers:
                return []

            # daily_opens from hot cache
            opens_df = result_df[result_df['timestamp'].dt.date == target_date][['ticker', 'open']].copy()
            opens_df = opens_df.rename(columns={'open': 'day_open'})

            # FASE 2: intraday_1m query (sin daily_opens CTE — el merge es en pandas)
            placeholders = ','.join(['?'] * len(tickers))
            con = get_db_connection(read_only=True)
            intra_query = f"""
                SELECT i.timestamp, i.ticker, i.close
                FROM intraday_1m i
                WHERE i.date = CAST(? AS DATE)
                AND i.ticker IN ({placeholders})
            """
            intra_rows = con.execute(intra_query, [target_date] + tickers).fetchall()

            if not intra_rows:
                return []

            intraday_df = pd.DataFrame(intra_rows, columns=['timestamp', 'ticker', 'close'])
            intraday_df = intraday_df.merge(opens_df, on='ticker', how='inner')
            intraday_df['pct_change'] = (intraday_df['close'] - intraday_df['day_open']) / intraday_df['day_open'] * 100
            intraday_df['minute'] = pd.to_datetime(intraday_df['timestamp']).dt.strftime('%H:%M')
            grouped = intraday_df.groupby('minute').agg(
                avg_change=('pct_change', 'mean'),
                median_change=('pct_change', 'median')
            ).reset_index()

            result = []
            for _, r in grouped.iterrows():
                result.append({
                    "time": r['minute'],
                    "avg_change": safe_float(r['avg_change']),
                    "median_change": safe_float(r['median_change'])
                })
            return result

        # ── Normal GCS Path ──
        from app.services.query_service import build_aggregate_query
        con = get_db_connection(read_only=True)

        screener_query, sql_p = build_aggregate_query(filters)

        ticker_query = f"WITH screen_res AS ({screener_query}) SELECT ticker, gap_pct, timestamp FROM screen_res"
        cur = con.execute(ticker_query, sql_p)
        rows = cur.fetchall()

        if not rows:
            return []

        target_date = trade_date
        if not target_date and rows:
            if rows[0][2]:
                target_date = rows[0][2].date()

        if not target_date:
            return []

        tickers = list(set([r[0] for r in rows]))

        if not tickers:
            return []

        placeholders = ','.join(['?'] * len(tickers))

        agg_query = f"""
            WITH daily_opens AS (
                 SELECT ticker, open as day_open 
                 FROM daily_metrics 
                 WHERE DATE_TRUNC('day', timestamp) = CAST(? AS DATE)
                 AND ticker IN ({placeholders})
            ),
            joined_intraday AS (
                SELECT 
                    i.timestamp, i.ticker, i.close, d.day_open,
                    ((i.close - d.day_open) / d.day_open * 100) as pct_change
                FROM intraday_1m i
                JOIN daily_opens d ON i.ticker = d.ticker
                WHERE i.date = CAST(? AS DATE)
                AND i.ticker IN ({placeholders})
            )
            SELECT 
                strftime(timestamp, '%H:%M') as minute,
                AVG(pct_change) as avg_change,
                QUANTILE_CONT(pct_change, 0.5) as median_change
            FROM joined_intraday
            GROUP BY 1
            ORDER BY 1
        """

        params = [target_date] + tickers + [target_date] + tickers
        agg_cur = con.execute(agg_query, params)
        agg_rows = agg_cur.fetchall()

        result = []
        for r in agg_rows:
            result.append({
                "time": r[0],
                "avg_change": safe_float(r[1]),
                "median_change": safe_float(r[2])
            })
        return result

    except Exception as e:
        return []
    finally:
        if con: con.close()
