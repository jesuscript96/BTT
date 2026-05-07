
import duckdb
import pandas as pd
import os

# Find a sample parquet file
base_dir = "/Users/jvch/Downloads/Small Caps/Datos intradiarios/Datos descargados/1m"
files = [f for f in os.listdir(base_dir) if f.endswith('.parquet')]
if not files:
    print("No parquet files found")
    exit(1)

sample_file = os.path.join(base_dir, files[0])
print(f"Inspecting: {sample_file}")

# Use DuckDB to describe
con = duckdb.connect()
print("\n--- DuckDB Schema ---")
con.execute(f"DESCRIBE SELECT * FROM '{sample_file}'")
print(con.fetchall())

print("\n--- First 5 Rows ---")
df = con.execute(f"SELECT * FROM '{sample_file}' LIMIT 5").df()
print(df)
