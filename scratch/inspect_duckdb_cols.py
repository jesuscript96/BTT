import duckdb

con = duckdb.connect('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb')

print("Views:")
try:
    views = con.execute("SELECT view_name, schema_name FROM duckdb_views()").fetchall()
    for v in views:
        print(f"View: {v[1]}.{v[0]}")
except Exception as e:
    print(f"Error: {e}")

con.close()
