import sys
import os
import pandas as pd
import duckdb

sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.database import get_db_connection
from app.init_db import init_db

init_db()

con = get_db_connection(read_only=True)
try:
    # Let's query one of the tickers that has min_gap >= 15
    # Find active tickers for a target date
    res = con.execute("""
        SELECT ticker, timestamp, open, prev_close
        FROM daily_metrics
        WHERE gap_pct >= 15
        ORDER BY timestamp DESC
        LIMIT 5
    """).fetchall()
    
    print("Top daily metrics matching gap_pct >= 15:")
    for row in res:
        ticker, ts, o, pc = row
        print(f"Ticker: {ticker}, Date: {ts}, Open: {o}, Prev Close (close_4am): {pc}")
        
        # Now query the intraday prices around 09:30 for this ticker
        date_str = str(ts.date())
        intra = con.execute("""
            SELECT timestamp, open, high, low, close, volume
            FROM intraday_1m
            WHERE ticker = ? AND date = ? AND strftime(timestamp, '%H:%M') BETWEEN '09:28' AND '09:32'
            ORDER BY timestamp ASC
        """, [ticker, date_str]).fetchall()
        print("  Intraday 1m around 09:30:")
        for r in intra:
            print(f"    Time: {r[0]}, Open: {r[1]}, High: {r[2]}, Low: {r[3]}, Close: {r[4]}, Vol: {r[5]}")
            
finally:
    con.close()
