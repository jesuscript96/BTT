import os
import sys
import time
import pandas as pd
import duckdb
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(env_path)

from app.services.cache_service import load_hot_daily_cache, get_hot_daily_cache
from app.database import get_db_connection

def compute_price_change_chart_optimized(ticker: str, dates: list) -> list:
    if not dates:
        return []
    
    con = get_db_connection()
    
    ym_dates = {}
    for d_str in dates:
        dt = pd.to_datetime(d_str)
        ym_dates.setdefault((dt.year, dt.month), []).append(d_str)
        
    clauses = []
    for (y, m), ds in ym_dates.items():
        date_list_str = ", ".join(f"DATE '{d}'" for d in ds)
        clauses.append(f"(year = {y} AND month = {m} AND CAST(date AS DATE) IN ({date_list_str}))")
    
    if not clauses:
        return []
    
    partition_filter = " OR ".join(clauses)
    
    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    
    if provider == "gcs":
        bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
        paths = [f"gs://{bucket}/cold_storage/intraday_1m/year={y}/month={m}/*.parquet" for y, m in ym_dates.keys()]
        query = f"""
            SELECT timestamp, open, close, high, low, volume, CAST(date AS VARCHAR) as date_str
            FROM read_parquet(?, hive_partitioning=true)
            WHERE ticker = ?
              AND ({partition_filter})
            ORDER BY timestamp ASC
        """
        params = [paths, ticker]
    else:
        query = f"""
            SELECT timestamp, open, close, high, low, volume, CAST(date AS VARCHAR) as date_str
            FROM intraday_1m
            WHERE ticker = ?
              AND ({partition_filter})
            ORDER BY timestamp ASC
        """
        params = [ticker]
        
    try:
        df = con.execute(query, params).fetchdf()
    except Exception as e:
        print(f"Error fetching intraday: {e}")
        return []
        
    if df.empty:
        return []
        
    rth_opens = {}
    try:
        dm_clauses = []
        for (y, m), ds in ym_dates.items():
            date_list_str = ", ".join(f"DATE '{d}'" for d in ds)
            dm_clauses.append(f"(year = {y} AND month = {m} AND CAST(timestamp AS DATE) IN ({date_list_str}))")
        dm_filter = " OR ".join(dm_clauses)
        
        if provider == "gcs":
            bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
            dm_paths = [f"gs://{bucket}/cold_storage/daily_metrics/year={y}/month={m}/*.parquet" for y, m in ym_dates.keys()]
            dm_query = f"""
                SELECT CAST(timestamp AS VARCHAR)[:10] as date_str, rth_open
                FROM read_parquet(?, hive_partitioning=true)
                WHERE ticker = ? AND ({dm_filter})
            """
            dm_df = con.execute(dm_query, [dm_paths, ticker]).fetchdf()
        else:
            dm_query = f"""
                SELECT CAST(timestamp AS VARCHAR)[:10] as date_str, rth_open
                FROM daily_metrics
                WHERE ticker = ? AND ({dm_filter})
            """
            dm_df = con.execute(dm_query, [ticker]).fetchdf()
            
        for _, row in dm_df.iterrows():
            rth_opens[row['date_str']] = row['rth_open']
    except Exception as e:
        print(f"Error fetching rth_opens: {e}")
        
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    grouped = df.groupby('date_str')
    
    def get_time_bin(dt):
        hour = dt.hour
        minute = dt.minute
        if hour < 4 or hour >= 16:
            return None
        bin_start_min = (minute // 15) * 15
        bin_end_min = bin_start_min + 15
        
        start_str = f"{hour:02d}:{bin_start_min:02d}"
        if bin_end_min == 60:
            end_str = f"{(hour+1):02d}:00"
        else:
            end_str = f"{hour:02d}:{bin_end_min:02d}"
            
        is_pre = (hour < 9) or (hour == 9 and minute < 30)
        return f"{start_str}-{end_str}", is_pre

    all_bins_data = []
    
    for date_str, group in grouped:
        rth_open = rth_opens.get(date_str)
        if not rth_open or pd.isna(rth_open):
            rth_bars = group[group['timestamp'].dt.time >= pd.to_datetime('09:30:00').time()]
            if not rth_bars.empty:
                rth_open = rth_bars.iloc[0]['open']
            else:
                rth_open = group.iloc[0]['open']
                
        if not rth_open or rth_open == 0:
            continue
            
        for _, row in group.iterrows():
            ts = row['timestamp']
            close = row['close']
            
            bin_info = get_time_bin(ts)
            if bin_info:
                bin_name, is_pre = bin_info
                change_pct = (close - rth_open) / rth_open * 100
                all_bins_data.append({
                    "bin": bin_name,
                    "is_pre": is_pre,
                    "change_pct": change_pct
                })
                
    if not all_bins_data:
        return []
        
    bins_df = pd.DataFrame(all_bins_data)
    summary = bins_df.groupby(['bin', 'is_pre'])['change_pct'].mean().reset_index()
    summary['sort_time'] = summary['bin'].apply(lambda x: x.split('-')[0])
    summary = summary.sort_values('sort_time').reset_index(drop=True)
    
    chart_data = []
    for _, row in summary.iterrows():
        chart_data.append({
            "bin": row['bin'],
            "avg_change_pct": float(row['change_pct']),
            "is_premarket": bool(row['is_pre'])
        })
        
    return chart_data

def get_gap_stats_all_days_optimized(ticker: str) -> dict:
    ticker = ticker.upper()
    df = pd.DataFrame()
    
    try:
        cache_df = get_hot_daily_cache()
        if cache_df is not None and not cache_df.empty:
            ticker_cache = cache_df[(cache_df['ticker'] == ticker) & (cache_df['pmh_gap_pct'] >= 20.0)]
            if ticker_cache.empty:
                empty_stats = {
                    "source": "database",
                    "gap_days_count": 0,
                    "high_rth_spike_avg": None,
                    "low_rth_spike_avg": None,
                    "pm_fade_avg": None,
                    "rthh_fade_avg": None,
                    "neg_close_freq": None,
                    "close_above_pmh_freq": None,
                    "close_below_vwap_freq": None,
                    "price_change_chart": []
                }
                return {
                    "gap_stats": empty_stats,
                    "gap_stats_plus_1": empty_stats,
                    "gap_stats_plus_2": empty_stats
                }
            
            needed_partitions = set()
            for timestamp in ticker_cache['timestamp']:
                dt = pd.to_datetime(timestamp)
                needed_partitions.add((dt.year, dt.month))
                next_day = dt + pd.Timedelta(days=5)
                needed_partitions.add((next_day.year, next_day.month))
                
            clauses = []
            for y, m in needed_partitions:
                clauses.append(f"(year = {y} AND month = {m})")
            partition_filter = " OR ".join(clauses)
            
            con = get_db_connection()
            provider = os.getenv("DB_PROVIDER", "motherduck").lower()
            
            if provider == "gcs":
                bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
                dm_paths = [f"gs://{bucket}/cold_storage/daily_metrics/year={y}/month={m}/*.parquet" for y, m in needed_partitions]
                query = f"""
                    SELECT * EXCLUDE (pmh_gap_pct), 
                           gap_pct AS gap_at_open_pct,
                           ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) as pmh_gap_pct
                    FROM read_parquet(?, hive_partitioning=true)
                    WHERE ticker = ? 
                      AND ({partition_filter})
                    ORDER BY timestamp ASC
                """
                df = con.execute(query, [dm_paths, ticker]).fetchdf()
            else:
                query = f"""
                    SELECT * FROM daily_metrics 
                    WHERE ticker = ? 
                      AND ({partition_filter})
                    ORDER BY timestamp ASC
                """
                df = con.execute(query, [ticker]).fetchdf()
    except Exception as e:
        print(f"Error querying optimized daily_metrics: {e}")
        
    if df.empty:
        return {}
        
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
    
    gap_indices = df[df['pmh_gap_pct'] >= 20.0].index.tolist() if 'pmh_gap_pct' in df.columns else []
    
    def compute_stats_for_offset(offset):
        target_indices = [idx + offset for idx in gap_indices if idx + offset < len(df)]
        if not target_indices:
            return {
                "source": "database",
                "gap_days_count": 0,
                "high_rth_spike_avg": None,
                "low_rth_spike_avg": None,
                "pm_fade_avg": None,
                "rthh_fade_avg": None,
                "neg_close_freq": None,
                "close_above_pmh_freq": None,
                "close_below_vwap_freq": None,
                "price_change_chart": []
            }
        
        sub_df = df.loc[target_indices].copy()
        
        o = sub_df['rth_open']
        h = sub_df['rth_high']
        l = sub_df['rth_low']
        c = sub_df['rth_close']
            
        high_spike = (h - o) / o * 100
        low_spike = (o - l) / o * 100
        rthh_fade = (h - c) / h * 100
        neg_close = (c < o).astype(float) * 100
        mid_point = (h + l) / 2.0
        close_below_vwap = (c < mid_point).astype(float) * 100
        
        pm_fade = None
        close_above_pmh = None
        if 'pm_high' in sub_df.columns:
            pm_h = sub_df['pm_high']
            pm_fade = (pm_h - o) / pm_h * 100
            pm_fade = pm_fade.mask(pm_h <= 0, None)
            close_above_pmh = (c > pm_h).astype(float) * 100
            close_above_pmh = close_above_pmh.mask(pm_h <= 0, None)
            
        target_dates = pd.to_datetime(sub_df['timestamp']).dt.strftime('%Y-%m-%d').tolist()
        chart_data = compute_price_change_chart_optimized(ticker, target_dates)
            
        def safe_mean(s):
            if s is None or s.empty:
                return None
            val = s.mean()
            return float(val) if not pd.isna(val) else None

        return {
            "source": "database",
            "gap_days_count": len(sub_df),
            "high_rth_spike_avg": safe_mean(high_spike),
            "low_rth_spike_avg": safe_mean(low_spike),
            "pm_fade_avg": safe_mean(pm_fade),
            "rthh_fade_avg": safe_mean(rthh_fade),
            "neg_close_freq": safe_mean(neg_close),
            "close_above_pmh_freq": safe_mean(close_above_pmh),
            "close_below_vwap_freq": safe_mean(close_below_vwap),
            "price_change_chart": chart_data
        }

    return {
        "gap_stats": compute_stats_for_offset(0),
        "gap_stats_plus_1": compute_stats_for_offset(1),
        "gap_stats_plus_2": compute_stats_for_offset(2)
    }

print("Loading hot cache...")
load_hot_daily_cache()
print("Starting AACG optimized stats query...")
t0 = time.time()
res = get_gap_stats_all_days_optimized("AACG")
print(f"Finished in {time.time() - t0:.2f}s!")
print("Day 0 gap days:", res['gap_stats']['gap_days_count'])
print("Day 0 price change chart length:", len(res['gap_stats']['price_change_chart']))
if len(res['gap_stats']['price_change_chart']) > 0:
    print("Day 0 price change chart sample:", res['gap_stats']['price_change_chart'][:3])
