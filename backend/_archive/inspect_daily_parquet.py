
import duckdb
import os

# Inspect a Daily file
daily_file = "/Users/jvch/Downloads/Small Caps/Datos diarios/AACB.parquet"
print(f"Inspecting Daily: {daily_file}")

con = duckdb.connect()
print("\n--- DuckDB Schema (Daily) ---")
con.execute(f"DESCRIBE SELECT * FROM '{daily_file}'")
print(con.fetchall())

print("\n--- First 5 Rows (Daily) ---")
df = con.execute(f"SELECT * FROM '{daily_file}' LIMIT 5").df()
print(df)
