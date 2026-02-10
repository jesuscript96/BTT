
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from datetime import date
from typing import List, Optional, Any
from app.database import get_db_connection
import pandas as pd
import numpy as np
import uuid

def safe_float(v):
    if v is None: return 0.0
    try:
        fv = float(v)
        if np.isnan(fv) or np.isinf(fv): return 0.0
        return fv
    except:
        return 0.0

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
            try:
                filtered_df = filtered_df[filtered_df['pm_volume'] >= float(query_params['min_pm_volume'])]
            except: pass
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
            
            # ARCHITECTURE FIX: Sample the dataset to 500 records to prevent OOM on Render Free Tier
            # 500 records is statistically significant for percentiles while keeping joins manageable.
            if len(df_set) > 500:
                df_set = df_set.sample(n=500, random_state=42)
            
            # Register scope for query with unique name for thread safety
            reg_name = f"subset_{uuid.uuid4().hex}"
            scope = df_set[['ticker', 'date', 'open', 'high', 'low', 'close', 'pm_high', 'prev_close', 'volume']].copy()
            scope['date'] = pd.to_datetime(scope['date']).dt.date
            con.register(reg_name, scope)
            
            # Intraday stats aggregation with refined timing and volume logic
            stats_query = f"""
                WITH dedup_intraday AS (
                    SELECT h.ticker, h.timestamp, h.open, h.high, h.low, h.close, h.volume, h.vwap
                    FROM intraday_1m h
                    JOIN {reg_name} fs ON h.ticker = fs.ticker AND CAST(h.timestamp AS DATE) = fs.date
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
                    JOIN {reg_name} f ON h.ticker = f.ticker AND CAST(h.timestamp AS DATE) = f.date
                    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
                ),
                raw_stats AS (
                    SELECT
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
                )
                SELECT 
                    'avg' as type,
                    AVG(pmh_gap_pct) as pmh_gap_pct,
                    AVG(pmh_fade_pct) as pmh_fade_pct,
                    AVG(rth_fade_pct) as rth_fade_pct,
                    AVG(rth_range_pct) as rth_range_pct,
                    AVG(open_lt_vwap_flag) as open_lt_vwap_flag,
                    AVG(pm_high_break_flag) as pm_high_break_flag,
                    AVG(close_red_flag) as close_red_flag,
                    AVG(low_spike_lt_pc_flag) as low_spike_lt_pc_flag,
                    AVG(pm_volume) as pm_volume,
                    AVG(pmh_price) as pmh_price,
                    AVG(open_price) as open_price,
                    AVG(close_price) as close_price,
                    AVG(m15_ret) as m15_ret,
                    AVG(m60_ret) as m60_ret,
                    AVG(m180_ret) as m180_ret,
                    AVG(close_ret) as close_ret,
                    AVG(high_spike_pct) as high_spike_pct,
                    AVG(low_spike_pct) as low_spike_pct,
                    MODE(hod_t) as hod_mode,
                    MODE(lod_t) as lod_mode
                FROM raw_stats
                UNION ALL
                SELECT 
                    'p50' as type,
                    QUANTILE_CONT(pmh_gap_pct, 0.5) as pmh_gap_pct,
                    QUANTILE_CONT(pmh_fade_pct, 0.5) as pmh_fade_pct,
                    QUANTILE_CONT(rth_fade_pct, 0.5) as rth_fade_pct,
                    QUANTILE_CONT(rth_range_pct, 0.5) as rth_range_pct,
                    QUANTILE_CONT(open_lt_vwap_flag, 0.5) as open_lt_vwap_flag,
                    QUANTILE_CONT(pm_high_break_flag, 0.5) as pm_high_break_flag,
                    QUANTILE_CONT(close_red_flag, 0.5) as close_red_flag,
                    QUANTILE_CONT(low_spike_lt_pc_flag, 0.5) as low_spike_lt_pc_flag,
                    QUANTILE_CONT(pm_volume, 0.5) as pm_volume,
                    QUANTILE_CONT(pmh_price, 0.5) as pmh_price,
                    QUANTILE_CONT(open_price, 0.5) as open_price,
                    QUANTILE_CONT(close_price, 0.5) as close_price,
                    QUANTILE_CONT(m15_ret, 0.5) as m15_ret,
                    QUANTILE_CONT(m60_ret, 0.5) as m60_ret,
                    QUANTILE_CONT(m180_ret, 0.5) as m180_ret,
                    QUANTILE_CONT(close_ret, 0.5) as close_ret,
                    QUANTILE_CONT(high_spike_pct, 0.5) as high_spike_pct,
                    QUANTILE_CONT(low_spike_pct, 0.5) as low_spike_pct,
                    '--' as hod_mode,
                    '--' as lod_mode
                FROM raw_stats
                UNION ALL
                SELECT 
                    'p25' as type,
                    QUANTILE_CONT(pmh_gap_pct, 0.25) as pmh_gap_pct,
                    QUANTILE_CONT(pmh_fade_pct, 0.25) as pmh_fade_pct,
                    QUANTILE_CONT(rth_fade_pct, 0.25) as rth_fade_pct,
                    QUANTILE_CONT(rth_range_pct, 0.25) as rth_range_pct,
                    QUANTILE_CONT(open_lt_vwap_flag, 0.25) as open_lt_vwap_flag,
                    QUANTILE_CONT(pm_high_break_flag, 0.25) as pm_high_break_flag,
                    QUANTILE_CONT(close_red_flag, 0.25) as close_red_flag,
                    QUANTILE_CONT(low_spike_lt_pc_flag, 0.25) as low_spike_lt_pc_flag,
                    QUANTILE_CONT(pm_volume, 0.25) as pm_volume,
                    QUANTILE_CONT(pmh_price, 0.25) as pmh_price,
                    QUANTILE_CONT(open_price, 0.25) as open_price,
                    QUANTILE_CONT(close_price, 0.25) as close_price,
                    QUANTILE_CONT(m15_ret, 0.25) as m15_ret,
                    QUANTILE_CONT(m60_ret, 0.25) as m60_ret,
                    QUANTILE_CONT(m180_ret, 0.25) as m180_ret,
                    QUANTILE_CONT(close_ret, 0.25) as close_ret,
                    QUANTILE_CONT(high_spike_pct, 0.25) as high_spike_pct,
                    QUANTILE_CONT(low_spike_pct, 0.25) as low_spike_pct,
                    '--' as hod_mode,
                    '--' as lod_mode
                FROM raw_stats
                UNION ALL
                SELECT 
                    'p75' as type,
                    QUANTILE_CONT(pmh_gap_pct, 0.75) as pmh_gap_pct,
                    QUANTILE_CONT(pmh_fade_pct, 0.75) as pmh_fade_pct,
                    QUANTILE_CONT(rth_fade_pct, 0.75) as rth_fade_pct,
                    QUANTILE_CONT(rth_range_pct, 0.75) as rth_range_pct,
                    QUANTILE_CONT(open_lt_vwap_flag, 0.75) as open_lt_vwap_flag,
                    QUANTILE_CONT(pm_high_break_flag, 0.75) as pm_high_break_flag,
                    QUANTILE_CONT(close_red_flag, 0.75) as close_red_flag,
                    QUANTILE_CONT(low_spike_lt_pc_flag, 0.75) as low_spike_lt_pc_flag,
                    QUANTILE_CONT(pm_volume, 0.75) as pm_volume,
                    QUANTILE_CONT(pmh_price, 0.75) as pmh_price,
                    QUANTILE_CONT(open_price, 0.75) as open_price,
                    QUANTILE_CONT(close_price, 0.75) as close_price,
                    QUANTILE_CONT(m15_ret, 0.75) as m15_ret,
                    QUANTILE_CONT(m60_ret, 0.75) as m60_ret,
                    QUANTILE_CONT(m180_ret, 0.75) as m180_ret,
                    QUANTILE_CONT(close_ret, 0.75) as close_ret,
                    QUANTILE_CONT(high_spike_pct, 0.75) as high_spike_pct,
                    QUANTILE_CONT(low_spike_pct, 0.75) as low_spike_pct,
                    '--' as hod_mode,
                    '--' as lod_mode
                FROM raw_stats
            """
            agg_df = con.execute(stats_query).fetch_df()
            if agg_df.empty: return {}

            # Pull Gap and Total Vol quantiles from daily df_set (lighter Pandas work)
            g_avg = float(df_set['gap_at_open_pct'].mean())
            g_p25 = float(df_set['gap_at_open_pct'].quantile(0.25))
            g_p50 = float(df_set['gap_at_open_pct'].quantile(0.50))
            g_p75 = float(df_set['gap_at_open_pct'].quantile(0.75))

            v_avg = float(df_set['volume'].mean())
            v_p25 = float(df_set['volume'].quantile(0.25))
            v_p50 = float(df_set['volume'].quantile(0.50))
            v_p75 = float(df_set['volume'].quantile(0.75))

            def row_to_dict(row, g_val, v_val):
                return {
                    "pm_high_gap_pct": safe_float(row['pmh_gap_pct']),
                    "pmh_fade_to_open_pct": safe_float(row['pmh_fade_pct']),
                    "rth_fade_to_close_pct": safe_float(row['rth_fade_pct']),
                    "rth_range_pct": safe_float(row['rth_range_pct']),
                    "open_lt_vwap": safe_float(row['open_lt_vwap_flag']),
                    "pm_high_break": safe_float(row['pm_high_break_flag']),
                    "close_red": safe_float(row['close_red_flag']),
                    "low_spike_lt_prev_close": safe_float(row['low_spike_lt_pc_flag']),
                    "avg_pm_volume": safe_float(row['pm_volume']),
                    "avg_pmh_price": safe_float(row['pmh_price']),
                    "avg_open_price": safe_float(row['open_price']),
                    "avg_close_price": safe_float(row['close_price']),
                    "m15_return_pct": safe_float(row['m15_ret']),
                    "m60_return_pct": safe_float(row['m60_ret']),
                    "m180_return_pct": safe_float(row['m180_ret']),
                    "return_close_pct": safe_float(row['close_ret']),
                    "high_spike_pct": safe_float(row['high_spike_pct']),
                    "low_spike_pct": safe_float(row['low_spike_pct']),
                    "gap_at_open_pct": safe_float(g_val),
                    "avg_volume": safe_float(v_val)
                }

            avg_row = agg_df[agg_df['type'] == 'avg'].iloc[0]
            p25_row = agg_df[agg_df['type'] == 'p25'].iloc[0]
            p50_row = agg_df[agg_df['type'] == 'p50'].iloc[0]
            p75_row = agg_df[agg_df['type'] == 'p75'].iloc[0]

            return { 
                "avg": row_to_dict(avg_row, g_avg, v_avg),
                "p25": row_to_dict(p25_row, g_p25, v_p25),
                "p50": row_to_dict(p50_row, g_p50, v_p50),
                "p75": row_to_dict(p75_row, g_p75, v_p75),
                "times": {
                    "hod": str(avg_row['hod_mode']),
                    "lod": str(avg_row['lod_mode'])
                }
            }

        # Calculate everything
        distributions = {"hod_time": {}, "lod_time": {}}
        stats_payload = { "count": len(filtered_df), "avg": {}, "p25": {}, "p50": {}, "p75": {}, "distributions": distributions }
        
        if not filtered_df.empty:
            try:
                p_stats = get_percentile_stats(filtered_df)
                if p_stats:
                    times_data = p_stats.pop('times', {"hod": "--", "lod": "--"})
                    stats_payload.update(p_stats)
                    
                    # Populate distributions with the mode times found (Convert keys to string for JSON)
                    distributions['hod_time'] = { str(times_data['hod']): 1.0 }
                    distributions['lod_time'] = { str(times_data['lod']): 1.0 }
                    stats_payload['distributions'] = distributions
            except Exception as e:
                print(f"CRITICAL: Stats calculation failed: {e}")
                import traceback
                traceback.print_exc()

        # 6. Pagination and Return
        limited_df = filtered_df.head(limit)
        records = []
        for _, row in limited_df.iterrows():
            records.append({
                "ticker": row.get('ticker', '--'),
                "date": str(row.get('date', '')),
                "open": safe_float(row.get('open', 0)),
                "high": safe_float(row.get('high', 0)),
                "low": safe_float(row.get('low', 0)),
                "close": safe_float(row.get('close', 0)),
                "volume": safe_float(row.get('volume', 0)),
                "gap_at_open_pct": safe_float(row.get('gap_at_open_pct', 0)),
                "rth_run_pct": safe_float(row.get('rth_run_pct', 0)),
                "day_return_pct": safe_float(row.get('day_return_pct', 0)),
                "pmh_gap_pct": safe_float(row.get('pmh_gap_pct', 0)),
                "pmh_fade_pct": safe_float(row.get('pmh_fade_to_open_pct', 0)),
                "rth_fade_pct": safe_float(row.get('rth_fade_to_close_pct', 0))
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
        
        # JSON Safety: Replace NaN/Inf
        df = df.replace([np.inf, -np.inf], np.nan).fillna(0)
        
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
        
        # ARCHITECTURE FIX: Sample the dataset to 500 records for the aggregate chart
        if len(f_df) > 500:
            f_df = f_df.sample(n=500, random_state=42)
            
        reg_name = f"scope_{uuid.uuid4().hex}"
        scope = f_df[['ticker', 'date', 'open']].rename(columns={'open': 'rth_open'})
        scope['date'] = pd.to_datetime(scope['date']).dt.date
        con.register(reg_name, scope)
        
        agg_query = f"""
            SELECT 
                strftime(h.timestamp, '%H:%M') as time,
                AVG( (h.close - f.rth_open) / f.rth_open * 100 ) as avg_change,
                MEDIAN( (h.close - f.rth_open) / f.rth_open * 100 ) as median_change
            FROM intraday_1m h
            JOIN {reg_name} f ON h.ticker = f.ticker AND CAST(h.timestamp AS DATE) = f.date
            WHERE h.timestamp IS NOT NULL
            GROUP BY 1 ORDER BY 1 ASC
        """
        df_agg = con.execute(agg_query).fetch_df()
        # JSON Safety: Handle Inf and NaN for standard JSON compliance
        df_agg = df_agg.replace([np.inf, -np.inf], np.nan)
        return df_agg.where(pd.notna(df_agg), None).to_dict(orient="records")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if con: con.close()
