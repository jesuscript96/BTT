import pandas as pd
import duckdb

ticker = "KIDZ"

print("--- Querying all daily_metrics rows for KIDZ from DuckDB (Read-Only) ---")
try:
    # Connect directly to users.duckdb in read-only mode to avoid locking issues
    con = duckdb.connect('users.duckdb', read_only=True)
    df_db = con.execute("SELECT timestamp, open, close, gap_pct FROM daily_metrics WHERE ticker = ? ORDER BY timestamp ASC", [ticker]).fetchdf()
    print("Total rows in DB:", len(df_db))
    db_gaps = df_db[df_db['gap_pct'] >= 20.0]
    print("Gaps >= 20% in DB:")
    for idx, row in db_gaps.iterrows():
         print(f"  {row['timestamp']} | Gap: {row['gap_pct']:.2f}% | Open: {row['open']} | Close: {row['close']}")
    con.close()
except Exception as e:
    print("Error querying database directly:", e)
