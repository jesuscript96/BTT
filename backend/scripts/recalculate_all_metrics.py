import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
import numpy as np
# Setup paths
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)
load_dotenv()

from app.database import get_db_connection
from app.processor import process_daily_metrics

def recalculate_all():
    print("🚀 Starting MASS Metric Recalculation...")
    con = get_db_connection()
    
    # 1. Get list of tickers that have historical data
    tickers = con.execute("SELECT DISTINCT ticker FROM historical_data").fetch_df()['ticker'].tolist()
    print(f"📊 Found {len(tickers)} tickers to process.")
    
    for ticker in tickers:
        print(f"Processing {ticker}...")
        try:
            # 2. Fetch all historical data for this ticker
            df = con.execute("SELECT * FROM historical_data WHERE ticker = ? ORDER BY timestamp ASC", [ticker]).fetch_df()
            if df.empty:
                continue
                
            # 3. Calculate metrics
            # This handles multi-day data automatically
            metrics_df = process_daily_metrics(df)
            
            if metrics_df.empty:
                continue
                
            # 4. Upsert using DELETE-THEN-INSERT for MotherDuck compatibility
            for _, row in metrics_df.iterrows():
                ticker_val = row['ticker']
                date_val = row['date']
                
                # Delete existing
                con.execute("DELETE FROM daily_metrics WHERE ticker = ? AND date = ?", [ticker_val, date_val])
                
                # Insert new
                cols = list(row.index)
                vals = [row[c] for c in cols]
                placeholders = ", ".join(["?"] * len(cols))
                col_names = ", ".join(cols)
                
                # Sanitize values (Numpy types to native Python, and Inf/NaN to None)
                sanitized_vals = []
                for v in vals:
                    if pd.isna(v) or (isinstance(v, float) and (v == float('inf') or v == float('-inf'))):
                        sanitized_vals.append(None)
                    elif hasattr(v, 'item'):  # Handle numpy types (.item() returns native)
                        val = v.item()
                        # Final check for nan/inf on the unwrapped value if it's a float
                        if isinstance(val, float) and (not np.isfinite(val)):
                            sanitized_vals.append(None)
                        else:
                            sanitized_vals.append(val)
                    else:
                        sanitized_vals.append(v)
                
                con.execute(f"INSERT INTO daily_metrics ({col_names}) VALUES ({placeholders})", sanitized_vals)
                
        except Exception as e:
            print(f"❌ Error processing {ticker}: {e}")
            continue

    con.close()
    print("\n✅ MASS Recalculation Complete!")

if __name__ == "__main__":
    recalculate_all()
