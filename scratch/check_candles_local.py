import duckdb
import pandas as pd
import numpy as np

# Connect to local users.duckdb
con = duckdb.connect('c:\\Users\\Famil\\OneDrive\\Escritorio\\Jaume\\Edgecute Jaume\\BTT\\users.duckdb')

try:
    df = con.execute("""
        SELECT timestamp, open, high, low, close, volume 
        FROM intraday_1m 
        WHERE ticker = 'AEI' AND CAST(timestamp AS DATE) = '2025-01-02'
        ORDER BY timestamp
    """).fetchdf()
    print(f"Direct local query loaded {len(df)} candles.")
    if len(df) > 0:
        print(df.head(20))
    else:
        print("No rows returned from direct local query.")
except Exception as e:
    print(f"Error: {e}")
con.close()
