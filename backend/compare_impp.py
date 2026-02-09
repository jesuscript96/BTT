
import duckdb
import os
import pandas as pd

# Daily file
daily_file = "/Users/jvch/Downloads/Small Caps/Datos diarios/IMPP.parquet"
con = duckdb.connect()
print(f"--- Daily Range for IMPP ---")
try:
    df_daily = con.execute(f"SELECT MIN(timestamp) as start, MAX(timestamp) as end, COUNT(*) as count FROM '{daily_file}'").df()
    print(df_daily)
except Exception as e:
    print(f"Error reading daily: {e}")

# Check for 1m files for IMPP
intraday_dir = "/Users/jvch/Downloads/Small Caps/Datos intradiarios/Datos descargados/1m"
impp_files = [f for f in os.listdir(intraday_dir) if f.startswith("IMPP_")]
print(f"\n--- Intraday Files for IMPP ---")
print(f"Found {len(impp_files)} files")
if impp_files:
    impp_files.sort()
    print(f"First: {impp_files[0]}")
    print(f"Last: {impp_files[-1]}")
else:
    print("No intraday files found for IMPP")
