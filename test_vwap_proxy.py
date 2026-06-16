import random

# Let's write a test that reads some intraday data for a ticker and date and compares actual VWAP close with proxies.
import sys
import os
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.db.connection import get_connection

con = get_connection()
bucket = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')

# Let's query intraday data for a month and calculate actual VWAP and compare with proxies
try:
    path = f"gs://{bucket}/cold_storage/intraday_1m/year=2022/month=1/*.parquet"
    print("Fetching intraday data for comparison...")
    
    # Get all bars for AAPL in Jan 2022
    df = con.execute(f"""
        SELECT date, timestamp, open, high, low, close, volume
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE ticker = 'AAPL' AND volume > 0
        ORDER BY timestamp
    """).fetchdf()
    
    print(f"Loaded {len(df)} bars.")
    
    # Group by date
    grouped = df.groupby('date')
    
    total_days = 0
    actual_below_vwap = 0
    proxy_mid_below = 0
    proxy_typical_below = 0
    proxy_ohlc4_below = 0
    
    matches_mid = 0
    matches_typical = 0
    matches_ohlc4 = 0
    
    for date, group in grouped:
        total_days += 1
        
        # Calculate actual VWAP
        highs = group['high'].values
        lows = group['low'].values
        closes = group['close'].values
        volumes = group['volume'].values
        
        typical = (highs + lows + closes) / 3.0
        actual_vwap = (typical * volumes).sum() / volumes.sum()
        
        daily_close = closes[-1]
        daily_high = highs.max()
        daily_low = lows.min()
        daily_open = group['open'].values[0]
        
        is_actual_below = daily_close < actual_vwap
        
        # Proxy 1: Mid point
        mid_point = (daily_high + daily_low) / 2.0
        is_mid_below = daily_close < mid_point
        
        # Proxy 2: Typical Price
        typical_price = (daily_high + daily_low + daily_close) / 3.0
        is_typical_below = daily_close < typical_price
        
        # Proxy 3: OHLC4
        ohlc4 = (daily_open + daily_high + daily_low + daily_close) / 4.0
        is_ohlc4_below = daily_close < ohlc4
        
        if is_actual_below:
            actual_below_vwap += 1
        if is_mid_below:
            proxy_mid_below += 1
        if is_typical_below:
            proxy_typical_below += 1
        if is_ohlc4_below:
            proxy_ohlc4_below += 1
            
        if is_actual_below == is_mid_below:
            matches_mid += 1
        if is_actual_below == is_typical_below:
            matches_typical += 1
        if is_actual_below == is_ohlc4_below:
            matches_ohlc4 += 1
            
        print(f"Date {date}: Close={daily_close:.2f} | VWAP={actual_vwap:.2f} | Mid={mid_point:.2f} | Typ={typical_price:.2f} | OHLC4={ohlc4:.2f}")
        print(f"  Actual Below={is_actual_below} | Mid Below={is_mid_below} | Typ Below={is_typical_below} | OHLC4 Below={is_ohlc4_below}")
        
    print("\nSUMMARY:")
    print(f"Total days analyzed: {total_days}")
    print(f"Actual days below VWAP: {actual_below_vwap} ({actual_below_vwap/total_days*100:.1f}%)")
    print(f"Mid-point Proxy: {proxy_mid_below} days below ({proxy_mid_below/total_days*100:.1f}%) | Matches actual in {matches_mid/total_days*100:.1f}% of days")
    print(f"Typical Price Proxy: {proxy_typical_below} days below ({proxy_typical_below/total_days*100:.1f}%) | Matches actual in {matches_typical/total_days*100:.1f}% of days")
    print(f"OHLC4 Proxy: {proxy_ohlc4_below} days below ({proxy_ohlc4_below/total_days*100:.1f}%) | Matches actual in {matches_ohlc4/total_days*100:.1f}% of days")
    
except Exception as e:
    print(f"Error: {e}")

con.close()
