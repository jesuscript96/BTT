import duckdb
import json

con = duckdb.connect('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb', read_only=True)

print("Saved queries list:")
queries = con.execute("SELECT id, name, created_at FROM saved_queries ORDER BY created_at DESC").fetchall()
for q in queries[:10]:
    print(f"  {q[0]} | {q[1]} | {q[2]}")

print("\nDetail for 895fa968-3d15-447c-be83-411300cbcb88:")
q_row = con.execute("SELECT filters FROM saved_queries WHERE id = '895fa968-3d15-447c-be83-411300cbcb88'").fetchone()
if q_row:
    print("  Filters:", q_row[0])
else:
    print("  Not found in saved_queries")

pairs_row = con.execute("SELECT count(*), count(distinct ticker) FROM dataset_pairs WHERE dataset_id = '895fa968-3d15-447c-be83-411300cbcb88'").fetchone()
if pairs_row:
    print("  Pairs count:", pairs_row[0], "| Unique tickers:", pairs_row[1])
else:
    print("  Not found in dataset_pairs")

precache_row = con.execute("SELECT * FROM precache_state WHERE dataset_id = '895fa968-3d15-447c-be83-411300cbcb88'").fetchone()
if precache_row:
    print("  Precache state:", precache_row)
else:
    print("  Not found in precache_state")

con.close()
