import sys
import os
import time
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.db.connection import get_connection

con = get_connection()
bucket = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')

ticker = "AAPL"
print(f"Finding gap days for {ticker} using optimized glob...")

t0 = time.time()
try:
    # 1. Query daily_metrics using optimized glob
    daily_path = f"gs://{bucket}/cold_storage/daily_metrics/year=*/month=*/*.parquet"
    
    gap_days = con.execute(f"""
        SELECT 
            CAST(timestamp AS DATE) as date_str,
            gap_pct,
            pmh_gap_pct,
            rth_close,
            pm_high,
            prev_close,
            rth_open,
            rth_high,
            rth_low
        FROM read_parquet('{daily_path}', hive_partitioning=true)
        WHERE ticker = '{ticker}'
          AND (abs(gap_pct) >= 2.0 OR abs(pmh_gap_pct) >= 2.0)
        ORDER BY date_str
    """).fetchall()
    
    print(f"Found {len(gap_days)} gap days in {time.time() - t0:.2f}s")
    if not gap_days:
        print("No gap days found.")
        con.close()
        sys.exit(0)
        
    # Group dates by year and month to minimize files read
    from collections import defaultdict
    ym_dates = defaultdict(list)
    for row in gap_days:
        d = row[0] # date object
        ym_dates[(d.year, d.month)].append(d.strftime("%Y-%m-%d"))
        
    print("Dates by year-month:", dict(ym_dates))
    
    # 2. Query intraday_1m for those specific dates only
    total_below_vwap = 0
    total_valid_days = 0
    
    t_intraday_start = time.time()
    for (y, m), dates in ym_dates.items():
        # Glob path for this month
        intra_path = f"gs://{bucket}/cold_storage/intraday_1m_optimized/year={y}/month={m:02d}/*.parquet"
        # Check if optimized exists, if not use raw
        try:
            exists = con.execute(f"SELECT count(*) FROM glob('{intra_path}')").fetchall()[0][0] > 0
        except:
            exists = False
        if not exists:
            intra_path = f"gs://{bucket}/cold_storage/intraday_1m/year={y}/month={m:02d}/*.parquet"
            
        print(f"Reading from {intra_path} for dates {dates}...")
        
        date_list_str = ", ".join(f"'{d}'" for d in dates)
        
        # Calculate VWAP for each date in this month
        day_vwaps = con.execute(f"""
            SELECT 
                date,
                SUM((high + low + close) / 3.0 * volume) / SUM(volume) as vwap,
                ARGMAX(close, timestamp) as rth_close
            FROM read_parquet('{intra_path}', hive_partitioning=true)
            WHERE ticker = '{ticker}'
              AND date IN ({date_list_str})
              AND volume > 0
            GROUP BY date
        """).fetchall()
        
        for date_str, vwap, rth_close in day_vwaps:
            total_valid_days += 1
            is_below = rth_close < vwap
            if is_below:
                total_below_vwap += 1
            print(f"  {date_str}: Close={rth_close:.2f}, VWAP={vwap:.2f} | Below VWAP={is_below}")
            
    print(f"Intraday reading completed in {time.time() - t_intraday_start:.2f}s")
    if total_valid_days > 0:
        pct = (total_below_vwap / total_valid_days) * 100
        print(f"Percentage of days closed below VWAP: {pct:.2f}% ({total_below_vwap}/{total_valid_days})")
    else:
        print("No valid intraday data found.")
        
except Exception as e:
    print(f"Error: {e}")

con.close()
