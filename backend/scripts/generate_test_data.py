import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import duckdb
import os
import json

def generate_mock_data():
    tickers = ['AAPL', 'TSLA', 'NVDA', 'BTC']
    date_str = "2026-01-01"
    start_time = datetime.strptime(f"{date_str} 04:00", "%Y-%m-%d %H:%M") # Start PM
    
    intraday_rows = []
    
    for ticker in tickers:
        print(f"Generating data for {ticker}...")
        current_price = 150.0 if ticker != 'BTC' else 50000.0
        
        # 500 minutes of data
        for i in range(500):
            timestamp = start_time + timedelta(minutes=i)
            
            # Simple walk with some patterns
            change = np.random.normal(0, 0.2)
            
            # Add specific patterns for testing indicators
            if ticker == 'AAPL' and 100 < i < 150: # Bullish Cross Pattern
                change += 0.1
            if ticker == 'TSLA' and 200 < i < 250: # Exhaustion Streak
                change -= 0.3
            if ticker == 'NVDA' and i > 300: # Mean Reversion / AVWAP test
                dist = current_price - 150.0
                change -= dist * 0.01 
            
            open_p = current_price
            high_p = open_p + abs(np.random.normal(0, 0.1))
            low_p = open_p - abs(np.random.normal(0, 0.1))
            close_p = open_p + change
            current_price = close_p
            
            volume = np.random.randint(1000, 10000)
            
            intraday_rows.append({
                'ticker': ticker,
                'volume': volume,
                'open': open_p,
                'close': close_p,
                'high': high_p,
                'low': low_p,
                'timestamp': timestamp,
                'transactions': np.random.randint(10, 100),
                'date': timestamp.date()
            })
            
    df_intraday = pd.DataFrame(intraday_rows)
    
    # Process Daily Metrics using the app's processor
    import sys
    sys.path.append(os.path.abspath('backend'))
    from app.processor import process_daily_metrics
    
    # Mock connection for prev_close
    class MockCon:
        def execute(self, query, params):
            return self
        def fetchone(self):
            return (145.0,)
            
    daily_dfs = []
    for ticker in tickers:
        ticker_df = df_intraday[df_intraday['ticker'] == ticker]
        daily_dfs.append(process_daily_metrics(ticker_df, con=MockCon()))
        
    df_daily = pd.concat(daily_dfs)
    
    # Ensure daily timestamp is correct for MotherDuck (might need to be datetime or date)
    # df_daily['timestamp'] is already pd.Timestamp(date)
    
    # Save to local duckdb
    db_path = "backend/market_data_test.duckdb"
    if os.path.exists(db_path):
        os.remove(db_path)
        
    con = duckdb.connect(db_path)
    con.register('intraday_view', df_intraday)
    con.execute("CREATE TABLE intraday_1m AS SELECT * FROM intraday_view")
    
    con.register('daily_view', df_daily)
    con.execute("CREATE TABLE daily_metrics AS SELECT * FROM daily_view")
    
    print(f"Generated {len(df_intraday)} intraday rows and {len(df_daily)} daily metric rows.")
    print(f"Saved to {db_path}")
    con.close()

if __name__ == "__main__":
    generate_mock_data()
