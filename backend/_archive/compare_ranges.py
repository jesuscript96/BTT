
import duckdb
import os
import pandas as pd

# Daily file
daily_file = "/Users/jvch/Downloads/Small Caps/Datos diarios/AACB.parquet"
con = duckdb.connect()
print(f"--- Daily Range for AACB ---")
try:
    df_daily = con.execute(f"SELECT MIN(timestamp) as start, MAX(timestamp) as end, COUNT(*) as count FROM '{daily_file}'").df()
    print(df_daily)
except Exception as e:
    print(f"Error reading daily: {e}")

# Check for 1m files for AACB
intraday_dir = "/Users/jvch/Downloads/Small Caps/Datos intradiarios/Datos descargados/1m"
aacb_files = [f for f in os.listdir(intraday_dir) if f.startswith("AACB_")]
print(f"\n--- Intraday Files for AACB ---")
print(f"Found {len(aacb_files)} files")
if aacb_files:
    # Sort to find range
    aacb_files.sort()
    print(f"First: {aacb_files[0]}")
    print(f"Last: {aacb_files[-1]}")
else:
    print("No intraday files found for AACB")
