import os
import sys
# Add backend to path so we can import app
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

import pandas as pd
import json

def compute_price_change_chart(ticker: str, dates: list) -> list:
    if not dates:
        return []
    
    from app.database import get_db_connection
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
    
    query = f"""
        SELECT timestamp, open, close, high, low, volume, CAST(date AS VARCHAR) as date_str
        FROM intraday_1m
        WHERE ticker = ?
          AND ({partition_filter})
        ORDER BY timestamp ASC
    """
    
    try:
        df = con.execute(query, [ticker]).fetchdf()
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

# Test it for SPCX
dates = ["2021-10-05"]
res = compute_price_change_chart("SPCX", dates)
print(f"Result length: {len(res)}")
if res:
    print("First 5 bins:")
    print(res[:5])
    print("Last 5 bins:")
    print(res[-5:])
con = get_db_connection()
con.close()
