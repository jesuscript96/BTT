import duckdb

con = duckdb.connect('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb')
print("Tables in users.duckdb:")
tables = con.execute("PRAGMA show_tables").fetchall()
for t in tables:
    table_name = t[0]
    print(f"\nTable: {table_name}")
    try:
        cols = con.execute(f"PRAGMA table_info({table_name})").fetchall()
        for col in cols:
            # col[1] is column name, col[2] is type
            print(f"  - {col[1]} ({col[2]})")
    except Exception as e:
        print(f"  Error getting columns: {e}")

con.close()
