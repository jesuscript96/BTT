import os
import sys
from dotenv import load_dotenv
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.db.connection import get_connection
from app.services.data_service import fetch_qualifying_data, get_intraday_stream

def main():
    print("Analyzing GCS daily metrics and aftermarket crossings...")
    
    from app.database import get_user_db_connection, get_user_db_lock
    with get_user_db_lock():
        con = get_user_db_connection()
        queries = con.execute("SELECT id, name FROM saved_queries LIMIT 5").fetchall()
        con.close()
    if not queries:
        print("No saved queries found in users.duckdb!")
        return
    
    dataset_id = queries[0][0]
    print(f"Using dataset_id: {dataset_id}")
    
    qualifying_df = fetch_qualifying_data(dataset_id)
    if qualifying_df.empty:
        print("Qualifying DF is empty!")
        return
        
    qualifying_df['date'] = pd.to_datetime(qualifying_df['timestamp']).dt.strftime('%Y-%m-%d')
    date_from = qualifying_df['date'].dropna().min()
    date_to = qualifying_df['date'].dropna().max()
    print(f"Date range: {date_from} to {date_to}")
    
    stream = get_intraday_stream(qualifying_df, date_from, date_to)
    
    # We will aggregate:
    # 1. Total post-market bars analyzed
    # 2. Number of days where post-market price crossed above rth_high
    # 3. Number of days where post-market price crossed below rth_low
    
    total_days = 0
    days_above_rth_high = 0
    days_below_rth_low = 0
    
    qual_lookup = {
        (r["ticker"], str(r["date"])[:10]): r
        for r in qualifying_df.to_dict(orient="records")
    }
    
    for (date_raw, ticker_raw), day_df in stream:
        ticker = str(ticker_raw)
        date = str(date_raw)[:10]
        daily_stats = qual_lookup.get((ticker, date), {})
        if not daily_stats:
            continue
            
        rth_high = daily_stats.get('rth_high')
        rth_low = daily_stats.get('rth_low')
        if pd.isna(rth_high) or pd.isna(rth_low):
            continue
            
        # Post-market bars: 16:00 to 20:00
        day_df['time'] = pd.to_datetime(day_df['timestamp']).dt.time
        post_bars = day_df[(day_df['time'] >= pd.Timestamp("16:00").time()) & (day_df['time'] < pd.Timestamp("20:00").time())]
        
        if post_bars.empty:
            continue
            
        total_days += 1
        
        # Check high
        post_max_high = post_bars['high'].max()
        post_min_low = post_bars['low'].min()
        
        crossed_high = post_max_high > rth_high
        crossed_low = post_min_low < rth_low
        
        if crossed_high:
            days_above_rth_high += 1
        if crossed_low:
            days_below_rth_low += 1
            
        if total_days <= 10:
            print(f"Day {total_days}: {ticker} on {date} - RTH High: {rth_high}, RTH Low: {rth_low} | PMax: {post_max_high}, PMin: {post_min_low} | Crossed High: {crossed_high}, Crossed Low: {crossed_low}")
            
    print("\n--- Summary ---")
    print(f"Total days analyzed with aftermarket data: {total_days}")
    print(f"Days where aftermarket price crossed above RTH High: {days_above_rth_high} ({days_above_rth_high/total_days*100:.1f}%)")
    print(f"Days where aftermarket price crossed below RTH Low: {days_below_rth_low} ({days_below_rth_low/total_days*100:.1f}%)")

if __name__ == "__main__":
    main()
