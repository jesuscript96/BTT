import duckdb
import json

db_path = r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users.duckdb'
con = duckdb.connect(db_path, read_only=True)
print("Tables in users.duckdb:")
try:
    tables = con.execute("SHOW TABLES").fetchall()
    for t in tables:
        print(f"  {t[0]}")
except Exception as e:
    print(f"Error listing tables: {e}")

print("\nSaved queries:")
try:
    queries = con.execute("SELECT id, name, filters FROM saved_queries").fetchall()
    for q_id, name, filters in queries:
        print(f"Query ID: {q_id}, Name: {name}")
        print(f"Filters: {filters}")
        print("-" * 50)
except Exception as e:
    print(f"Error listing queries: {e}")

con.close()
