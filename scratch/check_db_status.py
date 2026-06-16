import duckdb
import json

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb'
print(f"Connecting to {db_path}...")
con = duckdb.connect(db_path, read_only=True)

print("\n--- Saved Queries (Datasets) ---")
try:
    queries = con.execute("SELECT id, name, created_at FROM saved_queries").fetchall()
    for q in queries:
        print(f"ID: {q[0]} | Name: {q[1]} | Created: {q[2]}")
except Exception as e:
    print(f"Error reading saved_queries: {e}")

print("\n--- Precache State ---")
try:
    states = con.execute("SELECT dataset_id, status, progress_pct, updated_at FROM precache_state").fetchall()
    for s in states:
        print(f"Dataset ID: {s[0]} | Status: {s[1]} | Progress: {s[2]}% | Updated: {s[3]}")
except Exception as e:
    print(f"Error reading precache_state: {e}")

print("\n--- Dataset Pairs Count ---")
try:
    counts = con.execute("SELECT dataset_id, count(*) FROM dataset_pairs GROUP BY dataset_id").fetchall()
    for c in counts:
        print(f"Dataset ID: {c[0]} | Pairs count: {c[1]}")
except Exception as e:
    print(f"Error reading dataset_pairs: {e}")

con.close()
