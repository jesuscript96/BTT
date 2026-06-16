import os
import sys
from dotenv import load_dotenv

# Add parent directory (backend) to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

load_dotenv()

# Set env variables if needed
os.environ["DISABLE_GCS_SYNC"] = "true"

from app.services.data_service import fetch_qualifying_data, get_intraday_stream
from app.services.backtest_service import _build_qualifying_lookup
from app.services.indicators import compute_indicator

def main():
    print("Testing indicators loading and computation...")
    # Let's mock a simple dataset ID or get an existing one.
    # In BTT, what dataset IDs exist? Let's check users.duckdb saved_queries.
    import duckdb
    con = duckdb.connect("users.duckdb", read_only=True)
    queries = con.execute("SELECT id, name FROM saved_queries LIMIT 5").fetchall()
    print("Saved Queries in users.duckdb:", queries)
    if not queries:
        print("No saved queries found in users.duckdb!")
        return
    
    dataset_id = queries[0][0]
    print(f"Using dataset_id: {dataset_id}")
    
    # Let's fetch qualifying data
    qualifying_df = fetch_qualifying_data(dataset_id)
    print(f"Qualifying data rows: {len(qualifying_df)}")
    if qualifying_df.empty:
        print("Qualifying DF is empty!")
        return
        
    print("Columns in qualifying_df:", qualifying_df.columns.tolist())
    
    # Check if rth_high and rth_low columns are present and what they contain
    print("Checking RTH values in qualifying_df:")
    # Check non-null entries
    valid_rth = qualifying_df.dropna(subset=['rth_high', 'rth_low'])
    print(f"Non-null RTH rows count: {len(valid_rth)}")
    print(valid_rth[['ticker', 'timestamp', 'rth_high', 'rth_low']].head(10))
    
    # Ensure timestamp/date column is correctly typed
    qualifying_df['date'] = pd.to_datetime(qualifying_df['timestamp']).dt.strftime('%Y-%m-%d')
    print("Sample dates after conversion:", qualifying_df['date'].dropna().unique()[:10])
    
    # Build lookup
    qual_lookup = _build_qualifying_lookup(qualifying_df)
    
    # Get intraday stream for a few tickers
    date_from = qualifying_df['date'].dropna().min()
    date_to = qualifying_df['date'].dropna().max()
    print(f"Date range: {date_from} to {date_to}")
    
    stream = get_intraday_stream(qualifying_df, date_from, date_to)
    count = 0
    for (date_raw, ticker_raw), day_df in stream:
        count += 1
        if count > 5:
            break
            
        ticker = str(ticker_raw)
        date = str(date_raw)[:10]
        daily_stats = qual_lookup.get((ticker, date), {})
        
        print(f"\n--- Day {count}: {ticker} on {date} ---")
        print("daily_stats keys:", list(daily_stats.keys()))
        print(f"daily_stats['rth_high']: {daily_stats.get('rth_high')}")
        print(f"daily_stats['rth_low']: {daily_stats.get('rth_low')}")
        
        # Test indicators
        df_bars = day_df.sort_values("timestamp").reset_index(drop=True)
        rth_high_series = compute_indicator("RTH High", df_bars, daily_stats=daily_stats)
        rth_low_series = compute_indicator("RTH Low", df_bars, daily_stats=daily_stats)
        
        print(f"Computed RTH High Series Sample: {rth_high_series.head(3).tolist()} (Length: {len(rth_high_series)})")
        print(f"Computed RTH Low Series Sample: {rth_low_series.head(3).tolist()} (Length: {len(rth_low_series)})")

if __name__ == "__main__":
    main()
