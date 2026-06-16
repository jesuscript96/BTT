import sys
import os
import pandas as pd

sys.path.append(os.path.abspath('backend'))
from dotenv import load_dotenv
load_dotenv('backend/.env')

from app.database import get_db_connection

conn = get_db_connection()

# Query intraday data for JFBR on 2026-01-16
try:
    path = "gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2026/month=1/*.parquet"
    intraday = conn.execute(f"""
        SELECT "timestamp", volume, close
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE ticker = 'JFBR' AND date = DATE '2026-01-16'
        ORDER BY "timestamp"
    """).fetchdf()
    
    print(f"Total bars found: {len(intraday)}")
    if not intraday.empty:
        intraday['cum_vol'] = intraday['volume'].cumsum()
        print("At 13:14:00:")
        target_row = intraday[intraday['timestamp'] == '2026-01-16 13:14:00']
        if not target_row.empty:
            print(target_row)
        else:
            print("13:14:00 bar not found, showing surrounding bars:")
            print(intraday[(intraday['timestamp'] >= '2026-01-16 13:10:00') & (intraday['timestamp'] <= '2026-01-16 13:20:00')])
        
        print("\nLast bar:")
        print(intraday.tail(1))
except Exception as e:
    print("Error:", e)
