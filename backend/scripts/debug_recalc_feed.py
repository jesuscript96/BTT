import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd

# Setup paths
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)
load_dotenv()

from app.database import get_db_connection
from app.processor import process_daily_metrics

def debug_feed():
    print("🚀 Debugging FEED Recalculation...")
    con = get_db_connection()
    
    ticker = 'FEED'
    # Fetch all historical data for this ticker
    df = con.execute("SELECT * FROM historical_data WHERE ticker = ? ORDER BY timestamp ASC", [ticker]).fetch_df()
    if df.empty:
        print("❌ No historical data found for FEED")
        return
        
    print(f"✅ Found {len(df)} 1m bars for FEED.")
    
    # Calculate metrics
    metrics_df = process_daily_metrics(df)
    
    if metrics_df.empty:
        print("❌ process_daily_metrics returned empty DataFrame")
        return
        
    print(f"✅ Calculated metrics for {len(metrics_df)} days.")
    print("\nSample processed data (latest day):")
    # Show columns of interest
    cols = ['date', 'gap_at_open_pct', 'pmh_gap_pct', 'low_spike_pct', 'hod_time', 'm15_return_pct']
    print(metrics_df[cols].tail(1))
    
    # Test saving for '2026-01-28'
    row = metrics_df[metrics_df['date'] == pd.Timestamp('2026-01-28').date()].iloc[0]
    ticker_val = row['ticker']
    date_val = row['date']
    
    print(f"\nAttempting to save FEED for {date_val}...")
    con.execute("DELETE FROM daily_metrics WHERE ticker = ? AND date = ?", [ticker_val, date_val])
    
    cols_to_save = list(row.index)
    vals = [row[c] for c in cols_to_save]
    placeholders = ", ".join(["?"] * len(cols_to_save))
    col_names = ", ".join(cols_to_save)
    
    sanitized_vals = []
    for v in vals:
        if isinstance(v, float) and (pd.isna(v) or v == float('inf') or v == float('-inf')):
            sanitized_vals.append(None)
        else:
            sanitized_vals.append(v)
            
    con.execute(f"INSERT INTO daily_metrics ({col_names}) VALUES ({placeholders})", sanitized_vals)
    print("✅ Save command executed.")
    
    # Verify immediately
    res = con.execute("SELECT low_spike_pct FROM daily_metrics WHERE ticker = ? AND date = ?", [ticker_val, date_val]).fetchone()
    print(f"📊 Verified saved low_spike_pct: {res[0]}")

    con.close()

if __name__ == "__main__":
    debug_feed()
