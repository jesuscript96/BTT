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
    sys.stdout.flush()
    con = get_db_connection()
    print("✅ Connected to MotherDuck.")
    sys.stdout.flush()
    
    # 1. Get list of tickers that have historical data
    print("🔍 Fetching ticker list...")
    sys.stdout.flush()
    tickers = con.execute("SELECT DISTINCT ticker FROM historical_data").fetch_df()['ticker'].tolist()
    print(f"📊 Found {len(tickers)} tickers to process.")
    sys.stdout.flush()
    
    # 1.1 Get table schema to ensure correct column mapping
    table_info = con.execute("DESCRIBE daily_metrics").fetch_df()
    db_columns = table_info['column_name'].tolist()
    print(f"📋 Table schema has {len(db_columns)} columns.")
    sys.stdout.flush()
    
    for ticker in tickers:
        print(f"Processing {ticker}...")
        sys.stdout.flush()
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
                
            # 4. Enrich using UPDATE for MotherDuck compatibility
            # We already have metrics_df. We want to UPDATE existing rows in daily_metrics
            # with these new values, identifying them by (ticker, date).
            
            # Prepare data for DuckDB registration
            # Only include columns that we want to update (all except join keys)
            metrics_to_update = [c for c in db_columns if c in metrics_df.columns and c not in ['ticker', 'date']]
            final_df = metrics_df[['ticker', 'date'] + metrics_to_update].copy()
            
            for col in final_df.columns:
                if final_df[col].dtype == object:
                    continue
                if pd.api.types.is_float_dtype(final_df[col]):
                    final_df[col] = final_df[col].replace([np.inf, -np.inf], np.nan)
            
            con.register('temp_metrics_chunk', final_df)
            
            # Build the UPDATE clause
            # DuckDB supports: UPDATE tbl SET col = t.col FROM tmp t WHERE ...
            set_clause = ", ".join([f"{c} = t.{c}" for c in metrics_to_update])
            
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute(f"""
                    UPDATE daily_metrics 
                    SET {set_clause} 
                    FROM temp_metrics_chunk t 
                    WHERE daily_metrics.ticker = t.ticker 
                    AND daily_metrics.date = t.date
                """)
                con.execute("COMMIT")
                print(f"  ✨ Enriched {len(final_df)} days for {ticker}")
            except Exception as e:
                con.execute("ROLLBACK")
                print(f"  ❌ Surgical Update error for {ticker}: {e}")
            
            sys.stdout.flush()
        except Exception as e:
            print(f"❌ Error processing {ticker}: {e}")
            continue

    con.close()
    print("\n✅ MASS Recalculation Complete!")

if __name__ == "__main__":
    recalculate_all()
