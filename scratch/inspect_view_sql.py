import duckdb

con = duckdb.connect('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb')

try:
    sql = con.execute("SELECT sql FROM duckdb_views() WHERE view_name = 'daily_metrics'").fetchone()[0]
    print("SQL for main.daily_metrics:")
    print(sql)
except Exception as e:
    print(f"Error: {e}")

con.close()
