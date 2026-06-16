import sys
import os
import pandas as pd

sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.services.data_service import fetch_qualifying_data

def test_preconditions():
    print("Initializing test...")
    # Let's get the first saved query ID from GCS
    from app.db.gcs_cache import get_saved_queries_df
    queries = get_saved_queries_df()
    if queries.empty:
        print("Error: No saved queries found")
        return
    
    dataset_id = queries.iloc[0]["id"]
    print(f"Using dataset ID: {dataset_id}")
    
    # 1. Fetch raw qualifying data without preconditions
    print("\n--- Test 1: Fetching raw qualifying data ---")
    df_raw = fetch_qualifying_data(dataset_id)
    print(f"Raw count: {len(df_raw)}")
    if df_raw.empty:
        print("Warning: Raw dataframe is empty, cannot proceed with tests.")
        return
        
    print("Raw sample columns:", list(df_raw.columns)[:10])
    print("Raw sample rows:")
    print(df_raw[["ticker", "date", "rth_close", "rth_volume"]].head())

    # 2. Fetch with simple precondition (Volume > 1,000,000 on gap_day)
    print("\n--- Test 2: Precondition Volume > 1M ---")
    preconds = [
        {
            "id": "pc_1",
            "day": "gap_day",
            "metric": "volume",
            "operator": ">",
            "value": 1000000.0
        }
    ]
    df_vol = fetch_qualifying_data(dataset_id, preconditions=preconds)
    print(f"Filtered count: {len(df_vol)}")
    if not df_vol.empty:
        print("Min volume in filtered:", df_vol["rth_volume"].min())
        print(df_vol[["ticker", "date", "rth_close", "rth_volume"]].head())
        
    # 3. Fetch with apply_day = gap_1_day (should shift dates)
    print("\n--- Test 3: Date Shifting (Gap +1 Day) ---")
    df_shift = fetch_qualifying_data(dataset_id, apply_day='gap_1_day')
    print(f"Shifted count: {len(df_shift)}")
    if not df_shift.empty:
        print("Shifted vs original date comparison:")
        # We need to trace back. Since fetch_qualifying_data shifts date directly,
        # let's look at lead_timestamp_1 vs date
        print(df_shift[["ticker", "date", "lead_timestamp_1"]].head())

    # 4. Fetch with SMA precondition (Close > SMA 20 on gap_day)
    print("\n--- Test 4: SMA Precondition (Close > SMA 20) ---")
    preconds_sma = [
        {
            "id": "pc_sma",
            "day": "gap_day",
            "metric": "close_vs_sma",
            "operator": ">",
            "sma_period": 20
        }
    ]
    df_sma = fetch_qualifying_data(dataset_id, preconditions=preconds_sma)
    print(f"SMA Filtered count: {len(df_sma)}")
    if not df_sma.empty:
        print("Filtered columns:", [c for c in df_sma.columns if "sma" in c])
        print(df_sma[["ticker", "date", "rth_close", "sma_20"]].head())

if __name__ == "__main__":
    test_preconditions()
