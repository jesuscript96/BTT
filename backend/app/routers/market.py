
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from typing import List, Optional, Any
from datetime import date
from app.database import get_db_connection
import pandas as pd
import numpy as np


router = APIRouter(
    prefix="/api/market",
    tags=["market"]
)

VALID_METRICS = {
    "rth_open", "rth_high", "rth_low", "rth_close", "rth_volume",
    "gap_at_open_pct", "rth_run_pct", "pm_high", "pm_volume",
    "high_spike_pct", "low_spike_pct", "pmh_fade_to_open_pct",
    "rth_fade_to_close_pct", "open_lt_vwap", "pm_high_break",
    "m15_return_pct", "m30_return_pct", "m60_return_pct",
    "close_lt_m15", "close_lt_m30", "close_lt_m60",
    "hod_time", "lod_time", "close_direction",
    # TIER 1
    "prev_close", "pmh_gap_pct", "rth_range_pct", "day_return_pct", "pm_high_time",
    # TIER 2
    "m1_high_spike_pct", "m5_high_spike_pct", "m15_high_spike_pct", 
    "m30_high_spike_pct", "m60_high_spike_pct", "m180_high_spike_pct",
    "m1_low_spike_pct", "m5_low_spike_pct", "m15_low_spike_pct",
    "m30_low_spike_pct", "m60_low_spike_pct", "m180_low_spike_pct",
    # TIER 3
    "return_m15_to_close", "return_m30_to_close", "return_m60_to_close"
}

@router.get("/screener")
def screen_market(
    request: Request,
    min_gap: float = 0.0,
    max_gap: Optional[float] = None,
    min_run: float = 0.0,
    min_volume: float = 0.0,
    trade_date: Optional[date] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    ticker: Optional[str] = None,
    limit: int = 100
):
    """
    Filter tickers based on daily metrics calculated on-the-fly.
    
    New Architecture:
    1. Query raw OHLCV data from daily_metrics
    2. Calculate metrics on-the-fly (gap, rth_run, etc.)
    3. Apply filters
    4. Return results + detailed stats
    """
    con = None
    try:
        from app.calculations import calculate_daily_metrics
        
        con = get_db_connection(read_only=True)
        
        # 1. Build base query for raw data
        where_clauses_daily = []
        where_clauses_intraday = []
        params = []
        
        # Date filters
        if start_date and end_date:
            where_clauses_daily.append("d.date BETWEEN ? AND ?")
            where_clauses_intraday.append("CAST(h.timestamp AS DATE) BETWEEN ? AND ?")
            params.extend([start_date, end_date])
        elif trade_date:
            where_clauses_daily.append("d.date = ?")
            where_clauses_intraday.append("CAST(h.timestamp AS DATE) = ?")
            params.append(trade_date)
        
        # Ticker filter
        if ticker:
            where_clauses_daily.append("d.ticker = ?")
            where_clauses_intraday.append("h.ticker = ?")
            params.append(ticker.upper())
        
        where_daily = " AND ".join(where_clauses_daily) if where_clauses_daily else "1=1"
        where_intraday = " AND ".join(where_clauses_intraday) if where_clauses_intraday else "1=1"
        
        # Combine params since they are used twice (once in CTE, once in main SELECT)
        full_params = params + params

        # 2. Query data with Intraday Aggregation
        query = f"""
            WITH intraday_stats AS (
                SELECT 
                    h.ticker,
                    CAST(h.timestamp AS DATE) as d,
                    -- PM Metrics
                    SUM(CASE WHEN strftime(h.timestamp, '%H:%M') < '09:30' THEN h.volume END) as pm_volume,
                    MAX(CASE WHEN strftime(h.timestamp, '%H:%M') < '09:30' THEN h.high END) as pm_high,
                    -- Price at specific minutes
                    MAX(CASE WHEN strftime(h.timestamp, '%H:%M') = '09:45' THEN h.close END) as price_m15,
                    MAX(CASE WHEN strftime(h.timestamp, '%H:%M') = '10:00' THEN h.close END) as price_m30,
                    MAX(CASE WHEN strftime(h.timestamp, '%H:%M') = '10:30' THEN h.close END) as price_m60,
                    -- HOD/LOD
                    MAX(h.high) as day_high,
                    MIN(h.low) as day_low,
                    ARGMAX(h.high, strftime(h.timestamp, '%H:%M')) as hod_t,
                    ARGMIN(h.low, strftime(h.timestamp, '%H:%M')) as lod_t,
                    -- VWAP at open
                    FIRST(h.vwap) as vwap_at_open
                FROM intraday_1m h
                WHERE {where_intraday}
                GROUP BY 1, 2
            )
            SELECT 
                d.ticker,
                d.date,
                d.open,
                d.high,
                d.low,
                d.close,
                d.volume,
                d.vwap,
                i.pm_volume,
                i.pm_high,
                i.price_m15,
                i.price_m30,
                i.price_m60,
                i.hod_t as hod_time,
                i.lod_t as lod_time,
                i.vwap_at_open
            FROM daily_metrics d
            LEFT JOIN intraday_stats i ON d.ticker = i.ticker AND d.date = i.d
            WHERE {where_daily}
            ORDER BY d.date DESC
        """
        
        df = con.execute(query, full_params).fetch_df()
        
        if df.empty:
            return {
                "records": [],
                "stats": {
                    "count": 0,
                    "averages": {},
                    "distributions": {"hod_time": {}, "lod_time": {}}
                }
            }
        
        # 3. Calculate metrics on-the-fly and add intraday derived ones
        df = calculate_daily_metrics(df)
        
        # Add intraday-derived metrics to the dataframe for filtering
        df['pm_volume'] = df['pm_volume'].fillna(0)
        df['pm_high'] = df['pm_high'].fillna(0)
        
        df['pmh_fade_to_open_pct'] = np.where(df['pm_high'] > 0, ((df['open'] - df['pm_high']) / df['pm_high'] * 100), 0)
        df['m15_return_pct'] = np.where(df['price_m15'] > 0, ((df['price_m15'] - df['open']) / df['open'] * 100), 0)
        df['m30_return_pct'] = np.where(df['price_m30'] > 0, ((df['price_m30'] - df['open']) / df['open'] * 100), 0)
        df['m60_return_pct'] = np.where(df['price_m60'] > 0, ((df['price_m60'] - df['open']) / df['open'] * 100), 0)
        df['high_spike_pct'] = np.where(df['open'] > 0, ((df['high'] - df['open']) / df['open'] * 100), 0)
        df['low_spike_pct'] = np.where(df['open'] > 0, ((df['low'] - df['open']) / df['open'] * 100), 0)
        df['open_lt_vwap'] = (df['open'] < df['vwap_at_open']).astype(int)
        df['close_gt_vwap'] = (df['close'] > df['vwap']).astype(int)
        df['pm_high_break'] = (df['high'] > df['pm_high']).astype(int)

        # 4. Apply filters on calculated metrics
        filtered_df = df.copy()
        query_params = dict(request.query_params)
        
        if min_gap > 0:
            filtered_df = filtered_df[filtered_df['gap_at_open_pct'] >= min_gap]
        if max_gap is not None:
            filtered_df = filtered_df[filtered_df['gap_at_open_pct'] <= max_gap]
        if min_run > 0:
            filtered_df = filtered_df[filtered_df['rth_run_pct'] >= min_run]
        if min_volume > 0:
            filtered_df = filtered_df[filtered_df['volume'] >= min_volume]
        
        # Support specifically min_pm_volume and other named filters
        if 'min_pm_volume' in query_params:
            filtered_df = filtered_df[filtered_df['pm_volume'] >= float(query_params['min_pm_volume'])]
        if 'hod_after' in query_params:
            filtered_df = filtered_df[filtered_df['hod_time'] >= query_params['hod_after']]
        if 'lod_before' in query_params:
            filtered_df = filtered_df[filtered_df['lod_time'] <= query_params['lod_before']]
        if 'open_lt_vwap' in query_params:
            val = query_params['open_lt_vwap'].lower() == 'true'
            filtered_df = filtered_df[filtered_df['open_lt_vwap'] == (1 if val else 0)]
        if 'close_gt_vwap' in query_params:
            val = query_params['close_gt_vwap'].lower() == 'true'
            filtered_df = filtered_df[filtered_df['close_gt_vwap'] == (1 if val else 0)]

        # Dynamic filters
        for param_name, param_value in query_params.items():
            if param_name in ['limit', 'trade_date', 'start_date', 'end_date', 'ticker', 
                             'min_gap', 'max_gap', 'min_run', 'min_volume', 
                             'min_pm_volume', 'hod_after', 'lod_before', 'open_lt_vwap', 'close_gt_vwap']:
                continue
            if param_name.startswith('min_'):
                column_name = param_name[4:]
                if column_name in filtered_df.columns:
                    filtered_df = filtered_df[filtered_df[column_name] >= float(param_value)]
            elif param_name.startswith('max_'):
                column_name = param_name[4:]
                if column_name in filtered_df.columns:
                    filtered_df = filtered_df[filtered_df[column_name] <= float(param_value)]
        
        def get_percentile_stats(df_set: pd.DataFrame):
            if df_set.empty: return {}
            
            # Register scope for query
            scope = df_set[['ticker', 'date', 'open', 'high', 'low', 'close', 'pm_high', 'prev_close', 'volume']].copy()
            scope['date'] = pd.to_datetime(scope['date']).dt.date
            con.register('filtered_subset', scope)
            
            # Intraday stats aggregation with refined timing and volume logic
            stats_query = """
                WITH dedup_intraday AS (
                    SELECT h.ticker, h.timestamp, h.open, h.high, h.low, h.close, h.volume, h.vwap
                    FROM intraday_1m h
                    JOIN filtered_subset fs ON h.ticker = fs.ticker AND CAST(h.timestamp AS DATE) = fs.date
                    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
                ),
                day_metrics_rth AS (
                    SELECT
                        h.ticker, CAST(h.timestamp AS DATE) as d, 
                        f.open as d_open, f.high as d_high, f.low as d_low, f.close as d_close, 
                        f.pm_high as d_pmh, f.prev_close as d_pc, f.volume as d_total_vol,
                        -- RTH Volume
                        SUM(CASE WHEN strftime(h.timestamp, '%H:%M') >= '09:30' AND strftime(h.timestamp, '%H:%M') < '16:00' THEN h.volume END) as rth_v,
                        -- Returns at specific minutes (relative to Daily Open)
                        MAX(CASE WHEN strftime(h.timestamp, '%H:%M') = '09:45' THEN h.close END) as price_m15,
                        MAX(CASE WHEN strftime(h.timestamp, '%H:%M') = '10:30' THEN h.close END) as price_m60,
                        MAX(CASE WHEN strftime(h.timestamp, '%H:%M') = '12:30' THEN h.close END) as price_m180,
                        -- VWAP at Open
                        FIRST(h.vwap) as vwap_open,
                        -- Session Times (Strictly RTH)
                        ARGMAX(strftime(h.timestamp, '%H:%M'), CASE WHEN strftime(h.timestamp, '%H:%M') >= '09:30' AND strftime(h.timestamp, '%H:%M') < '16:00' THEN h.high END) as hod_t,
                        ARGMIN(strftime(h.timestamp, '%H:%M'), CASE WHEN strftime(h.timestamp, '%H:%M') >= '09:30' AND strftime(h.timestamp, '%H:%M') < '16:00' THEN h.low END) as lod_t
                    FROM dedup_intraday h
                    JOIN filtered_subset f ON h.ticker = f.ticker AND CAST(h.timestamp AS DATE) = f.date
                    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
                )
                SELECT
                    ticker, d,
                    ((d_pmh - d_pc) / d_pc * 100) as pmh_gap_pct,
                    ((d_open - d_pmh) / d_pmh * 100) as pmh_fade_pct,
                    ((d_close - d_high) / d_high * 100) as rth_fade_pct,
                    ((d_high - d_low) / d_low * 100) as rth_range_pct,
                    (CASE WHEN d_open < vwap_open THEN 100 ELSE 0 END) as open_lt_vwap_flag,
                    (CASE WHEN d_high > d_pmh THEN 100 ELSE 0 END) as pm_high_break_flag,
                    (CASE WHEN d_close < d_open THEN 100 ELSE 0 END) as close_red_flag,
                    (CASE WHEN d_low < d_pc THEN 100 ELSE 0 END) as low_spike_lt_pc_flag,
                    ((price_m15 - d_open) / d_open * 100) as m15_ret,
                    ((price_m60 - d_open) / d_open * 100) as m60_ret,
                    ((price_m180 - d_open) / d_open * 100) as m180_ret,
                    ((d_close - d_open) / d_open * 100) as close_ret,
                    ((d_high - d_open) / d_open * 100) as high_spike_pct,
                    ((d_low - d_open) / d_open * 100) as low_spike_pct,
                    (d_total_vol - COALESCE(rth_v, 0)) as pm_volume,
                    d_total_vol as total_volume,
                    d_pmh as pmh_price,
                    d_open as open_price,
                    d_close as close_price,
                    hod_t, lod_t
                FROM day_metrics_rth
            """
            records_df = con.execute(stats_query).fetch_df()
            if records_df.empty: return {}

            # Add daily metrics from original set if needed (like total volume)
            # Merging back helps ensure we have all fields
            
            def row_to_stats(series, gap_val, vol_val):
                return {
                    "pm_high_gap_pct": float(series['pmh_gap_pct']),
                    "pmh_fade_to_open_pct": float(series['pmh_fade_pct']),
                    "rth_fade_to_close_pct": float(series['rth_fade_pct']),
                    "rth_range_pct": float(series['rth_range_pct']),
                    "open_lt_vwap": float(series['open_lt_vwap_flag']),
                    "pm_high_break": float(series['pm_high_break_flag']),
                    "close_red": float(series['close_red_flag']),
                    "low_spike_lt_prev_close": float(series['low_spike_lt_pc_flag']),
                    "avg_pm_volume": float(series['pm_volume']),
                    "avg_pmh_price": float(series['pmh_price']),
                    "avg_open_price": float(series['open_price']),
                    "avg_close_price": float(series['close_price']),
                    "m15_return_pct": float(series['m15_ret']),
                    "m60_return_pct": float(series['m60_ret']),
                    "m180_return_pct": float(series['m180_ret']),
                    "return_close_pct": float(series['close_ret']),
                    "high_spike_pct": float(series['high_spike_pct']),
                    "low_spike_pct": float(series['low_spike_pct']),
                    "gap_at_open_pct": float(gap_val),
                    "avg_volume": float(vol_val)
                }

            # Calculate means and quantiles for records from intraday
            avg_row = records_df.mean(numeric_only=True)
            p25_row = records_df.quantile(0.25, numeric_only=True)
            p50_row = records_df.quantile(0.50, numeric_only=True)
            p75_row = records_df.quantile(0.75, numeric_only=True)

            # Pull Gap and Total Vol quantiles from daily df_set
            gap_stats = df_set['gap_at_open_pct'].agg(['mean', 'quantile']) 
            # Note: Pandas agg doesn't do multiple quantiles easily in one call like this, so:
            g_avg = float(df_set['gap_at_open_pct'].mean())
            g_p25 = float(df_set['gap_at_open_pct'].quantile(0.25))
            g_p50 = float(df_set['gap_at_open_pct'].quantile(0.50))
            g_p75 = float(df_set['gap_at_open_pct'].quantile(0.75))

            v_avg = float(df_set['volume'].mean())
            v_p25 = float(df_set['volume'].quantile(0.25))
            v_p50 = float(df_set['volume'].quantile(0.50))
            v_p75 = float(df_set['volume'].quantile(0.75))

            # Distribute times for the response
            hods = records_df['hod_t'].value_counts()
            lods = records_df['lod_t'].value_counts()

            return { 
                "avg": row_to_stats(avg_row, g_avg, v_avg),
                "p25": row_to_stats(p25_row, g_p25, v_p25),
                "p50": row_to_stats(p50_row, g_p50, v_p50),
                "p75": row_to_stats(p75_row, g_p75, v_p75),
                "times": {
                    "hod": hods.index[0] if not hods.empty else "--",
                    "lod": lods.index[0] if not lods.empty else "--"
                }
            }

        # Calculate everything
        distributions = {"hod_time": {}, "lod_time": {}}
        stats_payload = { "count": len(filtered_df), "avg": {}, "p25": {}, "p50": {}, "p75": {}, "distributions": distributions }
        
        if not filtered_df.empty:
            p_stats = get_percentile_stats(filtered_df)
            times_data = p_stats.pop('times', {"hod": "--", "lod": "--"})
            stats_payload.update(p_stats)
            
            # Populate distributions with the mode times found
            distributions['hod_time'] = { times_data['hod']: 1.0 }
            distributions['lod_time'] = { times_data['lod']: 1.0 }
            stats_payload['distributions'] = distributions

        # 6. Pagination and Return
        limited_df = filtered_df.head(limit)
        records = []
        for _, row in limited_df.iterrows():
            records.append({
                "ticker": row['ticker'], "date": str(row['date']),
                "open": float(row['open']), "high": float(row['high']),
                "low": float(row['low']), "close": float(row['close']),
                "volume": float(row['volume']),
                "gap_at_open_pct": float(row['gap_at_open_pct']),
                "rth_run_pct": float(row['rth_run_pct']),
                "day_return_pct": float(row['day_return_pct']),
                "pmh_gap_pct": float(row.get('pmh_gap_pct', 0)),
                "pmh_fade_pct": float(row.get('pmh_fade_to_open_pct', 0)),
                "rth_fade_pct": float(row.get('rth_fade_to_close_pct', 0))
            })
            
        return {
            "records": records,
            "stats": stats_payload
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/ticker/{ticker}/intraday")
def get_intraday_data(ticker: str, trade_date: Optional[date] = None):
    """
    Get 1-minute candles for a specific ticker and date from JAUME intraday_1m.
    """
    con = None
    try:
        con = get_db_connection(read_only=True)
        if not trade_date:
            latest = con.execute("SELECT MAX(CAST(timestamp AS DATE)) FROM intraday_1m WHERE ticker = ?", [ticker]).fetchone()
            if latest and latest[0]: trade_date = latest[0]
            else: return []

        query = """
            SELECT timestamp, open, high, low, close, volume, vwap
            FROM intraday_1m 
            WHERE ticker = ? AND CAST(timestamp AS DATE) = ?
            GROUP BY 1, 2, 3, 4, 5, 6, 7
            ORDER BY timestamp ASC
        """
        df = con.execute(query, [ticker, trade_date]).fetch_df()
        if df.empty: return []
        df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Intraday Error: {str(e)}")
    finally:
        if con: con.close()

@router.get("/latest-date")
def get_latest_market_date():
    con = None
    try:
        con = get_db_connection(read_only=True)
        latest = con.execute("SELECT MAX(date) FROM daily_metrics").fetchone()
        return {"date": str(latest[0])} if latest and latest[0] else {"date": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()

@router.get("/aggregate/intraday")
def get_aggregate_intraday(
    request: Request,
    min_gap: float = 0.0, max_gap: Optional[float] = None,
    min_run: float = 0.0, min_volume: float = 0.0,
    trade_date: Optional[date] = None, start_date: Optional[date] = None,
    end_date: Optional[date] = None, ticker: Optional[str] = None
):
    """
    Aggregate Returns using intraday_1m relative to RTH Open for a filtered subset.
    """
    con = None
    try:
        from app.calculations import calculate_daily_metrics
        con = get_db_connection(read_only=True)
        
        # 1. Build common filter logic (same as screener)
        where_clauses_daily = []
        where_clauses_intraday = []
        params = []
        
        if start_date and end_date:
            where_clauses_daily.append("d.date BETWEEN ? AND ?")
            where_clauses_intraday.append("CAST(h.timestamp AS DATE) BETWEEN ? AND ?")
            params.extend([start_date, end_date])
        elif trade_date:
            where_clauses_daily.append("d.date = ?")
            where_clauses_intraday.append("CAST(h.timestamp AS DATE) = ?")
            params.append(trade_date)
        if ticker:
            where_clauses_daily.append("d.ticker = ?")
            where_clauses_intraday.append("h.ticker = ?")
            params.append(ticker.upper())
        
        where_daily = " AND ".join(where_clauses_daily) if where_clauses_daily else "1=1"
        where_intraday = " AND ".join(where_clauses_intraday) if where_clauses_intraday else "1=1"
        full_params = params + params

        # Query raw data with PM metrics join
        query = f"""
            WITH intraday_stats AS (
                SELECT 
                    h.ticker, CAST(h.timestamp AS DATE) as d,
                    SUM(CASE WHEN strftime(h.timestamp, '%H:%M') < '09:30' THEN h.volume END) as pm_volume,
                    MAX(CASE WHEN strftime(h.timestamp, '%H:%M') < '09:30' THEN h.high END) as pm_high,
                    FIRST(h.vwap) as vwap_at_open
                FROM intraday_1m h
                WHERE {where_intraday}
                GROUP BY 1, 2
            )
            SELECT d.ticker, d.date, d.open, d.high, d.low, d.close, d.volume, d.vwap, i.pm_volume, i.pm_high, i.vwap_at_open
            FROM daily_metrics d
            LEFT JOIN intraday_stats i ON d.ticker = i.ticker AND d.date = i.d
            WHERE {where_daily}
        """
        df = con.execute(query, full_params).fetch_df()
        
        if df.empty: return []
        df = calculate_daily_metrics(df)
        
        # Add derived metrics for filtering
        df['pm_volume'] = df['pm_volume'].fillna(0)
        df['pm_high'] = df['pm_high'].fillna(0)
        df['open_lt_vwap'] = (df['open'] < df['vwap_at_open']).astype(int)
        
        # Apply filters
        f_df = df.copy()
        q_p = dict(request.query_params)
        if min_gap > 0: f_df = f_df[f_df['gap_at_open_pct'] >= min_gap]
        if max_gap is not None: f_df = f_df[f_df['gap_at_open_pct'] <= max_gap]
        if min_run > 0: f_df = f_df[f_df['rth_run_pct'] >= min_run]
        if min_volume > 0: f_df = f_df[f_df['volume'] >= min_volume]
        
        if 'min_pm_volume' in q_p:
            f_df = f_df[f_df['pm_volume'] >= float(q_p['min_pm_volume'])]
        if 'open_lt_vwap' in q_p:
            val = q_p['open_lt_vwap'].lower() == 'true'
            f_df = f_df[f_df['open_lt_vwap'] == (1 if val else 0)]
            
        # Dynamic filters
        for p_name, p_val in q_p.items():
            if p_name in ['limit', 'trade_date', 'start_date', 'end_date', 'ticker', 
                          'min_gap', 'max_gap', 'min_run', 'min_volume', 
                          'min_pm_volume', 'open_lt_vwap']:
                continue
            if p_name.startswith('min_') and p_name[4:] in f_df.columns:
                f_df = f_df[f_df[p_name[4:]] >= float(p_val)]
            elif p_name.startswith('max_') and p_name[4:] in f_df.columns:
                f_df = f_df[f_df[p_name[4:]] <= float(p_val)]
        
        if f_df.empty: return []
        
        scope = f_df[['ticker', 'date', 'open']].rename(columns={'open': 'rth_open'})
        scope['date'] = pd.to_datetime(scope['date']).dt.date
        con.register('filtered_scope', scope)
        
        agg_query = """
            SELECT 
                strftime(h.timestamp, '%H:%M') as time,
                AVG( (h.close - f.rth_open) / f.rth_open * 100 ) as avg_change,
                MEDIAN( (h.close - f.rth_open) / f.rth_open * 100 ) as median_change
            FROM intraday_1m h
            JOIN filtered_scope f ON h.ticker = f.ticker AND CAST(h.timestamp AS DATE) = f.date
            WHERE h.timestamp IS NOT NULL
            GROUP BY 1 ORDER BY 1 ASC
        """
        df_agg = con.execute(agg_query).fetch_df()
        return df_agg.where(pd.notna(df_agg), None).to_dict(orient="records")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()
