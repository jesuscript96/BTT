import duckdb
import json

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb'
con = duckdb.connect(db_path, read_only=True)

try:
    rows = con.execute("SELECT name, definition FROM strategies LIMIT 2").fetchall()
    for r in rows:
        print(f"Strategy Name: {r[0]}")
        print("Definition Keys:", json.loads(r[1]).keys())
        print(json.dumps(json.loads(r[1]), indent=2))
        print("="*40)
except Exception as e:
    print("Error:", e)

con.close()
