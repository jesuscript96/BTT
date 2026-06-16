import os
import sys
from dotenv import load_dotenv
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.database import get_user_db_connection, get_user_db_lock
from app.services.data_service import fetch_qualifying_data, get_intraday_stream

def main():
    with get_user_db_lock():
        con = get_user_db_connection()
        queries = con.execute("SELECT id, name FROM saved_queries LIMIT 5").fetchall()
        con.close()
        
    dataset_id = queries[0][0]
    qualifying_df = fetch_qualifying_data(dataset_id, apply_day='gap_day')
    qualifying_df = qualifying_df[(qualifying_df['ticker'] == 'MGRX') & (pd.to_datetime(qualifying_df['timestamp']).dt.strftime('%Y-%m-%d') == '2024-10-01')]
    
    if qualifying_df.empty:
        print("HOLO on 2024-10-01 not in qualifying dataset!")
        return
        
    rth_low = qualifying_df.iloc[0]['rth_low']
    rth_high = qualifying_df.iloc[0]['rth_high']
    print(f"HOLO 2024-10-01: RTH High = {rth_high}, RTH Low = {rth_low}")
    
    stream = get_intraday_stream(qualifying_df, '2024-10-01', '2024-10-01')
    for (date_raw, ticker_raw), day_df in stream:
        df = day_df.sort_values("timestamp").reset_index(drop=True)
        df['time'] = pd.to_datetime(df['timestamp']).dt.strftime('%H:%M')
        
        # Print RTH low and high from intraday bars
        rth_bars = df[(df['time'] >= '09:30') & (df['time'] < '16:00')]
        print(f"Intraday RTH range: High = {rth_bars['high'].max()}, Low = {rth_bars['low'].min()}")
        
        # Closes in postmarket below rth_low
        post_bars = df[(df['time'] >= '16:00') & (df['time'] < '20:00')]
        below_low = post_bars[post_bars['close'] < rth_low]
        print(f"Total postmarket bars: {len(post_bars)}")
        print(f"Postmarket bars below RTH Low ({rth_low}): {len(below_low)}")
        if not below_low.empty:
            print("Sample postmarket bars below RTH Low:")
            print(below_low[['time', 'open', 'high', 'low', 'close', 'volume']].head(10))
            
if __name__ == "__main__":
    main()
