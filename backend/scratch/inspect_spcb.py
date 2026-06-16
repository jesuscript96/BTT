import duckdb
try:
    con = duckdb.connect('users.duckdb', read_only=True)
    print("Tables:", con.execute("SHOW TABLES").fetchall())
    res = con.execute("SELECT COUNT(*) FROM daily_metrics WHERE ticker='SPCB'").fetchone()
    print("SPCB count in daily_metrics:", res)
    # Print a few columns and rows
    df = con.execute("SELECT timestamp, gap_pct, open, close FROM daily_metrics WHERE ticker='SPCB' ORDER BY timestamp ASC LIMIT 5").fetchdf()
    print(df)
    con.close()
except Exception as e:
    print("Error:", e)
