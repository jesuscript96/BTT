import os
import sys
from dotenv import load_dotenv
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.database import get_user_db_connection, get_user_db_lock
from app.services.data_service import fetch_qualifying_data

def main():
    print("Checking daily stats shifting for gap_1_day...")
    
    with get_user_db_lock():
        con = get_user_db_connection()
        queries = con.execute("SELECT id, name FROM saved_queries LIMIT 5").fetchall()
        con.close()
        
    if not queries:
        return
        
    dataset_id = queries[0][0]
    
    # Fetch with apply_day = 'gap_day'
    df_gap = fetch_qualifying_data(dataset_id, apply_day='gap_day')
    # Fetch with apply_day = 'gap_1_day'
    df_lead1 = fetch_qualifying_data(dataset_id, apply_day='gap_1_day')
    
    if df_gap.empty or df_lead1.empty:
        print("Dataframes are empty!")
        return
        
    print("\n--- GAP DAY ROW SAMPLE ---")
    print(df_gap[['ticker', 'date', 'rth_high', 'rth_low', 'lead_rth_high_1', 'lead_rth_low_1']].head(3))
    
    print("\n--- LEAD 1 DAY ROW SAMPLE ---")
    print(df_lead1[['ticker', 'date', 'rth_high', 'rth_low', 'lead_rth_high_1', 'lead_rth_low_1']].head(3))

if __name__ == "__main__":
    main()
