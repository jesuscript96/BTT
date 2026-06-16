import duckdb
import pandas as pd
import yfinance as yf
import os

ticker = "KIDZ"

print("--- YFINANCE 5Y HISTORICAL DATA ---")
try:
    stock = yf.Ticker(ticker)
    hist = stock.history(period="5y")
    if not hist.empty:
        hist = hist.reset_index()
        hist['prev_close'] = hist['Close'].shift(1)
        hist['gap_pct'] = (hist['Open'] - hist['prev_close']) / hist['prev_close'] * 100
        
        total_days = len(hist)
        all_gaps = hist[hist['gap_pct'] >= 20.0]
        
        print(f"Total days fetched from yfinance (5y): {total_days}")
        print(f"Number of gaps >= 20%: {len(all_gaps)}")
        if len(all_gaps) > 0:
            print("Gaps >= 20% details:")
            for idx, r in all_gaps.iterrows():
                print(f"  Date: {r['Date'].strftime('%Y-%m-%d')}, Open: {r['Open']:.2f}, Prev Close: {r['prev_close']:.2f}, Gap: {r['gap_pct']:.2f}%")
        
        # Let's check smaller gaps
        gaps_10 = hist[(hist['gap_pct'] >= 10.0) & (hist['gap_pct'] < 20.0)]
        print(f"Number of gaps between 10% and 20%: {len(gaps_10)}")
        if len(gaps_10) > 0:
            print("Gaps 10% - 20% details (first 5):")
            for idx, r in gaps_10.head(5).iterrows():
                print(f"  Date: {r['Date'].strftime('%Y-%m-%d')}, Open: {r['Open']:.2f}, Prev Close: {r['prev_close']:.2f}, Gap: {r['gap_pct']:.2f}%")
except Exception as e:
    print(f"yfinance error: {e}")


print("\n--- DATABASE daily_metrics DATA ---")
db_paths = [
    'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb',
    'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb'
]

for path in db_paths:
    if os.path.exists(path):
        print(f"\nChecking database at: {path}")
        try:
            # We try to connect. In case of lock, we report it.
            con = duckdb.connect(path, read_only=True)
            
            # Check row count for KIDZ
            rows = con.execute("SELECT COUNT(*) FROM daily_metrics WHERE ticker = ?", [ticker]).fetchone()[0]
            print(f"Total rows for {ticker} in daily_metrics: {rows}")
            
            if rows > 0:
                # Range
                date_range = con.execute("SELECT MIN(timestamp), MAX(timestamp) FROM daily_metrics WHERE ticker = ?", [ticker]).fetchone()
                print(f"Date Range: {date_range[0]} to {date_range[1]}")
                
                # Gaps >= 20% in database
                gaps = con.execute("SELECT timestamp, open, prev_close, gap_pct FROM daily_metrics WHERE ticker = ? AND gap_pct >= 20.0 ORDER BY timestamp ASC", [ticker]).fetchall()
                print(f"Number of gaps >= 20% in database: {len(gaps)}")
                for g in gaps:
                    print(f"  Date: {g[0]}, Open: {g[1]}, Prev Close: {g[2]}, Gap: {g[3]:.2f}%")
                
                # Check for smaller gaps in database
                gaps_10_db = con.execute("SELECT timestamp, open, prev_close, gap_pct FROM daily_metrics WHERE ticker = ? AND gap_pct >= 10.0 AND gap_pct < 20.0 ORDER BY timestamp ASC", [ticker]).fetchall()
                print(f"Number of gaps 10% - 20% in database: {len(gaps_10_db)}")
                for g in gaps_10_db[:5]:
                    print(f"  Date: {g[0]}, Open: {g[1]}, Prev Close: {g[2]}, Gap: {g[3]:.2f}%")
                    
            con.close()
        except Exception as e:
            print(f"Database error at {path}: {e}")
    else:
        print(f"Path does not exist: {path}")
