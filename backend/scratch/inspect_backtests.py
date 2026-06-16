import duckdb
import json

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb'
con = duckdb.connect(db_path)

try:
    print("=== Table: backtest_results ===")
    # Check column names first
    cols = con.execute("PRAGMA table_info(backtest_results)").fetchall()
    for col in cols:
        print(col)
        
    print("\nFetching last 10 backtest results:")
    rows = con.execute("SELECT * FROM backtest_results ORDER BY executed_at DESC LIMIT 10").fetchall()
    for r in rows:
        # Columns could vary, let's just print the raw row but restrict long fields
        print(f"ID/Name: {r[0] if len(r) > 0 else 'N/A'}, Created: {r[-1] if len(r) > 0 else 'N/A'}")
        print(str(r)[:500] + "...")
        print("-" * 40)
except Exception as e:
    print(f"Error: {e}")
finally:
    con.close()
