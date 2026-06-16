import duckdb
import json

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb'
con = duckdb.connect(db_path)

try:
    ds_id = 'bd49cdb9-a9ff-47d1-8455-061732c1166f'
    row = con.execute("SELECT filters FROM saved_queries WHERE id = ?", [ds_id]).fetchone()
    if row:
        print("Filters JSON:")
        filters = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        print(json.dumps(filters, indent=2))
    else:
        print("Dataset not found in saved_queries.")
except Exception as e:
    print(f"Error: {e}")
finally:
    con.close()
