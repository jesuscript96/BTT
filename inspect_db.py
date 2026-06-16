import duckdb

con = duckdb.connect('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb')

# Let's inspect views and tables metadata
print("Checking duckdb_views:")
try:
    views = con.execute("SELECT * FROM duckdb_views()").fetchall()
    for v in views:
        # v[1] is schema, v[2] is view_name, v[3] is sql
        print(f"View: {v[1]}.{v[2]}\nSQL: {v[3]}\n")
except Exception as e:
    print(f"Error checking views: {e}")

print("Checking duckdb_tables:")
try:
    tables = con.execute("SELECT * FROM duckdb_tables()").fetchall()
    for t in tables:
        # t[1] is schema, t[2] is table_name
        print(f"Table: {t[1]}.{t[2]}")
except Exception as e:
    print(f"Error checking tables: {e}")

con.close()
