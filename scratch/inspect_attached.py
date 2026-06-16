import duckdb

con = duckdb.connect('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb')

try:
    dbs = con.execute("PRAGMA database_list;").fetchall()
    print("Attached databases:")
    print(dbs)
except Exception as e:
    print(f"Error: {e}")

con.close()
