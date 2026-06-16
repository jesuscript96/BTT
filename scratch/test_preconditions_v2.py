import sys
import os
import pandas as pd

sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.services.data_service import fetch_qualifying_data

def test_preconditions_v2():
    print("Initializing test V2...")
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
        print("Warning: Raw dataframe is empty, cannot proceed.")
        return
        
    print("Raw sample rows:")
    print(df_raw[["ticker", "date", "rth_close", "rth_volume"]].head())

    # 2. Fetch with volume precondition: Volume > 1M on gap_day
    print("\n--- Test 2: Precondition Volume > 1M ---")
    preconds_vol = [
        {
            "id": "pc_vol_1",
            "day": "gap_day",
            "condition": {
                "type": "indicator_comparison",
                "source": {"name": "Volume", "offset": 0},
                "comparator": "GREATER_THAN",
                "target": 1000000
            }
        }
    ]
    df_vol = fetch_qualifying_data(dataset_id, preconditions=preconds_vol)
    print(f"Filtered count: {len(df_vol)}")
    if not df_vol.empty:
        print("Min volume in filtered:", df_vol["rth_volume"].min())
        print(df_vol[["ticker", "date", "rth_close", "rth_volume"]].head())

    # 3. Fetch with Close > SMA 20 on gap_day
    print("\n--- Test 3: SMA Precondition (Close > SMA 20) ---")
    preconds_sma = [
        {
            "id": "pc_sma_1",
            "day": "gap_day",
            "condition": {
                "type": "indicator_comparison",
                "source": {"name": "Bar Close", "offset": 0},
                "comparator": "GREATER_THAN",
                "target": {"name": "SMA", "period": 20, "offset": 0}
            }
        }
    ]
    df_sma = fetch_qualifying_data(dataset_id, preconditions=preconds_sma)
    print(f"SMA Filtered count: {len(df_sma)}")
    if not df_sma.empty:
        print("Columns starting with 'sma':", [c for c in df_sma.columns if "sma" in c])
        print(df_sma[["ticker", "date", "rth_close", "sma_20"]].head())

    # 4. Fetch with Close > Yesterday Close on gap_day (using offset=1)
    print("\n--- Test 4: Offset Precondition (Close > Yesterday Close) ---")
    preconds_offset = [
        {
            "id": "pc_offset_1",
            "day": "gap_day",
            "condition": {
                "type": "indicator_comparison",
                "source": {"name": "Bar Close", "offset": 0},
                "comparator": "GREATER_THAN",
                "target": {"name": "Bar Close", "offset": 1}
            }
        }
    ]
    df_offset = fetch_qualifying_data(dataset_id, preconditions=preconds_offset)
    print(f"Offset Filtered count: {len(df_offset)}")
    if not df_offset.empty:
        print(df_offset[["ticker", "date", "rth_close", "lag_rth_close_1"]].head())

    # 5. Fetch with Distance Precondition: Close is within 2% of Pre-market High
    print("\n--- Test 5: Distance Precondition (Close within 2% of Pre-market High) ---")
    preconds_dist = [
        {
            "id": "pc_dist_1",
            "day": "gap_day",
            "condition": {
                "type": "price_level_distance",
                "source": {"name": "Bar Close", "offset": 0},
                "level": {"name": "Pre-Market High", "offset": 0},
                "comparator": "DISTANCE_LESS_THAN",
                "value_pct": 2.0,
                "position": "any"
            }
        }
    ]
    df_dist = fetch_qualifying_data(dataset_id, preconditions=preconds_dist)
    print(f"Distance Filtered count: {len(df_dist)}")
    if not df_dist.empty:
        df_dist["calc_dist_pct"] = (abs(df_dist["rth_close"] - df_dist["pm_high"]) / df_dist["pm_high"]) * 100.0
        print(df_dist[["ticker", "date", "rth_close", "pm_high", "calc_dist_pct"]].head())

if __name__ == "__main__":
    test_preconditions_v2()
