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

def compute_price_change_chart_from_df(intraday_df: pd.DataFrame, rth_opens: dict, target_dates: list) -> list:
    if intraday_df.empty or not target_dates:
        return []
        
    df = intraday_df[intraday_df['date_str'].isin(target_dates)].copy()
    if df.empty:
        return []
        
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

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    grouped = df.groupby('date_str')
    
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

def get_gap_stats_all_days_pipeline(ticker: str) -> dict:
    ticker = ticker.upper()
    
    con = get_db_connection()
    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    
    # 1. Get cache and find gap days
    cache_df = get_hot_daily_cache()
    if cache_df is None or cache_df.empty:
        return {}
        
    t0 = time.time()
    df = cache_df[cache_df['ticker'] == ticker].copy()
    print(f"  [Profile] Load from in-memory cache took: {time.time() - t0:.4f}s, rows: {len(df)}")
    
    if df.empty:
        t0 = time.time()
        query = "SELECT * FROM daily_metrics WHERE ticker = ? ORDER BY timestamp ASC"
        df = con.execute(query, [ticker]).fetchdf()
        print(f"  [Profile] Fallback query daily_metrics took: {time.time() - t0:.2f}s")
        
    if df.empty:
        return {}
        
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        
    gap_indices = df[df['pmh_gap_pct'] >= 20.0].index.tolist() if 'pmh_gap_pct' in df.columns else []
    
    # Map out the date and dataframes for the 3 offsets
    offset_data = {}
    all_target_dates = set()
    
    recent_gap_indices = gap_indices[-5:] if len(gap_indices) > 5 else gap_indices
    recent_target_dates_map = {}
    
    for offset in [0, 1, 2]:
        target_indices = [idx + offset for idx in gap_indices if idx + offset < len(df)]
        if not target_indices:
            offset_data[offset] = {
                "sub_df": pd.DataFrame()
            }
            recent_target_dates_map[offset] = []
            continue
        sub_df = df.loc[target_indices].copy()
        offset_data[offset] = {
            "sub_df": sub_df
        }
        
        recent_target_indices = [idx + offset for idx in recent_gap_indices if idx + offset < len(df)]
        recent_sub_df = df.loc[recent_target_indices]
        recent_target_dates = pd.to_datetime(recent_sub_df['timestamp']).dt.strftime('%Y-%m-%d').tolist()
        all_target_dates.update(recent_target_dates)
        recent_target_dates_map[offset] = recent_target_dates
        
    rth_opens_map = {pd.to_datetime(row['timestamp']).strftime('%Y-%m-%d'): row['rth_open'] for _, row in df.iterrows() if not pd.isna(row['rth_open'])}
    
    # 3. Query intraday_1m ONCE for recent target dates (GCS optimization)
    intraday_df = pd.DataFrame()
    if all_target_dates:
        t0 = time.time()
        ym_dates = {}
        for d_str in all_target_dates:
            dt = pd.to_datetime(d_str)
            ym_dates.setdefault((dt.year, dt.month), []).append(d_str)
            
        intra_clauses = []
        for (y, m), ds in ym_dates.items():
            date_list_str = ", ".join(f"DATE '{d}'" for d in ds)
            intra_clauses.append(f"(year = {y} AND month = {m} AND CAST(date AS DATE) IN ({date_list_str}))")
        intra_filter = " OR ".join(intra_clauses)
        
        if provider == "gcs":
            bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
            raw_paths = [f"gs://{bucket}/cold_storage/intraday_1m/year={y}/month={m}/*.parquet" for y, m in ym_dates.keys()]
            
            # Check GCS paths via glob first
            valid_paths = []
            for path in raw_paths:
                try:
                    res = con.execute("SELECT file FROM glob(?)", [path]).fetchall()
                    if res:
                        valid_paths.append(path)
                except Exception as e:
                    print(f"Error globbing GCS path {path}: {e}")
                    
            if valid_paths:
                query = f"""
                    SELECT timestamp, open, close, high, low, volume, CAST(date AS VARCHAR) as date_str
                    FROM read_parquet(?, hive_partitioning=true)
                    WHERE ticker = ? AND ({intra_filter})
                    ORDER BY timestamp ASC
                """
                intraday_df = con.execute(query, [valid_paths, ticker]).fetchdf()
            else:
                print("No valid GCS paths found for the requested target dates.")
        else:
            query = f"""
                SELECT timestamp, open, close, high, low, volume, CAST(date AS VARCHAR) as date_str
                FROM intraday_1m
                WHERE ticker = ? AND ({intra_filter})
                ORDER BY timestamp ASC
            """
            intraday_df = con.execute(query, [ticker]).fetchdf()
        print(f"  [Profile] Query intraday_1m took: {time.time() - t0:.2f}s, paths: {len(ym_dates)}, rows: {len(intraday_df)}")
        
    # 4. Compute stats for each offset in-memory
    results = {}
    for offset in [0, 1, 2]:
        o_data = offset_data[offset]
        sub_df = o_data["sub_df"]
        recent_target_dates = recent_target_dates_map[offset]
        
        if sub_df.empty:
            results[f"gap_stats{'' if offset == 0 else f'_plus_{offset}'}"] = {
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
            continue
            
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
            
        chart_data = compute_price_change_chart_from_df(intraday_df, rth_opens_map, recent_target_dates)
            
        def safe_mean(s):
            if s is None or s.empty:
                return None
            val = s.mean()
            return float(val) if not pd.isna(val) else None

        results[f"gap_stats{'' if offset == 0 else f'_plus_{offset}'}"] = {
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
        
    return results

print("Loading hot cache...")
load_hot_daily_cache()
print("Starting VSME pipeline query...")
t0 = time.time()
res = get_gap_stats_all_days_pipeline("VSME")
print(f"Total time taken: {time.time() - t0:.2f}s")
print("Day 0 gap days:", res['gap_stats']['gap_days_count'])
print("Day 0 price change chart length:", len(res['gap_stats']['price_change_chart']))
if len(res['gap_stats']['price_change_chart']) > 0:
    print("Day 0 price change chart sample:", res['gap_stats']['price_change_chart'][:3])
