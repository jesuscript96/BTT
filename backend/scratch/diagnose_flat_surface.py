import duckdb
import json

db_copy_path = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users_copy.duckdb"
con = duckdb.connect(db_copy_path, read_only=True)
try:
    print("Saved Queries (Datasets):")
    df = con.execute("SELECT id, name, filters FROM saved_queries").fetchdf()
    for _, row in df.iterrows():
        print(f"ID: {row['id']} | Name: {row['name']}")
        print(f"  Filters: {row['filters']}")
        print("-" * 50)
finally:
    con.close()
