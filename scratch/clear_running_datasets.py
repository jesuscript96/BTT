import duckdb

con = duckdb.connect('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb')
try:
    rows = con.execute("UPDATE precache_state SET status = 'failed' WHERE status = 'running'").rowcount
    print(f"Successfully marked {rows} running datasets as 'failed'.")
    
    # Let's inspect the final states
    states = con.execute("SELECT dataset_id, status, progress_pct FROM precache_state").fetchall()
    print("Precache states:")
    for s in states:
        print(f"  ID: {s[0]} | Status: {s[1]} | Progress: {s[2]}%")
except Exception as e:
    print("Error:", e)
finally:
    con.close()
