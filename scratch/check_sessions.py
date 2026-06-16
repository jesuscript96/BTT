import sys
import os
sys.path.append(os.path.abspath('backend'))

from app.database import _establish_connection
from app.init_db import init_db

init_db()

con = _establish_connection()
try:
    # Find some tickers with intraday data
    print("Finding sample tickers and dates...")
    sample = con.execute("SELECT ticker, date, COUNT(*) FROM intraday_1m GROUP BY 1, 2 HAVING COUNT(*) > 100 LIMIT 5").fetchdf()
    print(sample)
    
    if not sample.empty:
        ticker = sample.iloc[0]['ticker']
        date = sample.iloc[0]['date']
        print(f"\nIntraday data for {ticker} on {date}:")
        data = con.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM intraday_1m WHERE ticker = ? AND date = ?", [ticker, date]).fetchdf()
        print(data)
        
        # Check distribution of hours
        hours = con.execute("""
            SELECT strftime(timestamp, '%H') as hour, COUNT(*) 
            FROM intraday_1m 
            WHERE ticker = ? AND date = ? 
            GROUP BY 1 
            ORDER BY 1
        """, [ticker, date]).fetchdf()
        print("\nHour distribution:")
        print(hours)
except Exception as e:
    print(f"Error: {e}")
finally:
    con.close()
