import duckdb

db_path = 'c:/Users/Famil/OneDrive\Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb'
print(f"Connecting to {db_path}...")
try:
    con = duckdb.connect(db_path, read_only=True)
    
    # Select 20 rows where pm_low and rth_low are non-null
    rows = con.execute("""
        SELECT ticker, timestamp, pm_high, pm_low, rth_high, rth_low, rth_open
        FROM main.daily_metrics
        WHERE pm_low IS NOT NULL AND rth_low IS NOT NULL AND pm_low > 0 AND rth_low > 0
        LIMIT 20
    """).fetchall()
    
    print("Found rows:")
    print(f"{'Ticker':<8} | {'Date/Time':<20} | {'PM High':<8} | {'PM Low':<8} | {'RTH High':<8} | {'RTH Low':<8} | {'RTH Open':<8}")
    print("-" * 85)
    for r in rows:
        print(f"{r[0]:<8} | {str(r[1]):<20} | {r[2]:<8.2f} | {r[3]:<8.2f} | {r[4]:<8.2f} | {r[5]:<8.2f} | {r[6]:<8.2f}")
        
    con.close()
except Exception as e:
    print(f"Error: {e}")
