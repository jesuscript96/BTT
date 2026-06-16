import duckdb
import json

con = duckdb.connect('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb', read_only=True)

try:
    print("--- 8 MOST RECENT DATASETS ---")
    rows = con.execute("""
        SELECT q.id, q.name, q.created_at, p.status, p.progress_pct, 
               (SELECT count(*) FROM dataset_pairs WHERE dataset_id = q.id) as pairs_count,
               q.filters
        FROM saved_queries q
        LEFT JOIN precache_state p ON q.id = p.dataset_id
        ORDER BY q.created_at DESC
        LIMIT 8
    """).fetchall()
    
    for r in rows:
        qid, name, created_at, status, pct, pairs_count, filters_json = r
        try:
            filters = json.loads(filters_json) if isinstance(filters_json, str) else filters_json
        except:
            filters = {}
        print(f"Name: {name}")
        print(f"  ID: {qid} | Created: {created_at}")
        print(f"  Pairs: {pairs_count} | Status: {status} ({pct}%)")
        print(f"  Filters: {filters}")
        print("-" * 60)
except Exception as e:
    print("Error:", e)
finally:
    con.close()
