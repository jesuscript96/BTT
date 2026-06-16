import os
import sys
from dotenv import load_dotenv
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.database import get_user_db_connection, get_user_db_lock
from app.services.data_service import fetch_qualifying_data, get_intraday_stream
from app.services.backtest_service import _build_qualifying_lookup

def main():
    print("Checking lookup keys type mismatch...")
    
    with get_user_db_lock():
        con = get_user_db_connection()
        queries = con.execute("SELECT id, name FROM saved_queries LIMIT 5").fetchall()
        con.close()
        
    dataset_id = queries[0][0]
    qualifying_df = fetch_qualifying_data(dataset_id, apply_day='gap_day')
    qualifying_df['date'] = pd.to_datetime(qualifying_df['timestamp']).dt.strftime('%Y-%m-%d')
    
    qual_lookup = _build_qualifying_lookup(qualifying_df)
    
    # Print some lookup keys and their types
    print("\nLookup keys sample:")
    sample_keys = list(qual_lookup.keys())[:5]
    for k in sample_keys:
        print(f"Key: {k} | Types: ({type(k[0])}, {type(k[1])})")
        
    date_from = qualifying_df['date'].dropna().min()
    date_to = qualifying_df['date'].dropna().max()
    
    stream = get_intraday_stream(qualifying_df, date_from, date_to)
    
    # Print some stream group keys and their types
    print("\nStream keys sample:")
    count = 0
    for (date_raw, ticker_raw), day_df in stream:
        count += 1
        print(f"Stream Key: ({ticker_raw}, {date_raw}) | Types: ({type(ticker_raw)}, {type(date_raw)})")
        
        # Test lookup get
        ds_raw = qual_lookup.get((ticker_raw, date_raw), {})
        ds_normalized = qual_lookup.get((str(ticker_raw), str(date_raw)[:10]), {})
        
        print(f"Lookup with raw key returned empty: {ds_raw == {}}")
        print(f"Lookup with normalized key returned empty: {ds_normalized == {}}")
        
        if count >= 3:
            break

if __name__ == "__main__":
    main()
