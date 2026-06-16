import duckdb

db_path = 'backend/app/market_data.db'
print(f"Connecting to local DuckDB at {db_path}...")
try:
    con = duckdb.connect(db_path, read_only=True)
    res = con.execute("SELECT timestamp FROM intraday_1m LIMIT 5").fetchall()
    print("Sample timestamps:")
    for r in res:
        print(r[0], type(r[0]))
    
    # Query data types
    schema = con.execute("DESCRIBE intraday_1m").fetchall()
    print("\nSchema:")
    for col in schema:
        print(f"  {col[0]}: {col[1]}")
    con.close()
except Exception as e:
    print("Error:", e)
