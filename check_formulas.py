import sys
import os
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.db.connection import get_connection

con = get_connection()
bucket = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')
path = f"gs://{bucket}/cold_storage/daily_metrics/year=2022/month=1/data_0.parquet"

try:
    # Let's get rows where pm_high and rth_high are present
    rows = con.execute(f"""
        SELECT ticker, timestamp, 
               pm_high, rth_open, rth_high, rth_low, rth_close, prev_close,
               pmh_fade_pct, rth_fade_pct, rth_run_pct
        FROM read_parquet('{path}')
        WHERE pm_high IS NOT NULL AND rth_high IS NOT NULL AND rth_open > 0 AND pm_high > 0
        LIMIT 5
    """).fetchall()
    
    for r in rows:
        ticker, ts, pm_high, rth_open, rth_high, rth_low, rth_close, prev_close, pmh_fade_pct, rth_fade_pct, rth_run_pct = r
        print(f"Ticker: {ticker} on {ts}")
        print(f"  Prices: pm_high={pm_high}, rth_open={rth_open}, rth_high={rth_high}, rth_low={rth_low}, rth_close={rth_close}, prev_close={prev_close}")
        
        # High spike formula: (rth_high - rth_open) / rth_open * 100
        calc_high_spike = (rth_high - rth_open) / rth_open * 100
        print(f"  High RTH spike calculated: {calc_high_spike:.4f}% | rth_run_pct: {rth_run_pct}")
        
        # Low spike formula: (rth_open - rth_low) / rth_open * 100
        calc_low_spike = (rth_open - rth_low) / rth_open * 100
        print(f"  Low RTH spike calculated: {calc_low_spike:.4f}%")
        
        # PM Fade: (pm_high - rth_open) / pm_high * 100
        calc_pm_fade = (pm_high - rth_open) / pm_high * 100
        print(f"  PM Fade calculated: {calc_pm_fade:.4f}% | pmh_fade_pct: {pmh_fade_pct}")
        
        # RTHH Fade: (rth_high - rth_close) / rth_high * 100
        calc_rth_fade_close = (rth_high - rth_close) / rth_high * 100
        calc_rth_fade_open = (rth_high - rth_open) / rth_high * 100
        print(f"  RTH Fade to Close calculated: {calc_rth_fade_close:.4f}% | RTH Fade to Open calculated: {calc_rth_fade_open:.4f}% | rth_fade_pct: {rth_fade_pct}")
        print("-" * 50)
        
except Exception as e:
    print(f"Error: {e}")

con.close()
