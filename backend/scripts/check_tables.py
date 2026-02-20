import sys
import os
sys.path.append(os.getcwd())
try:
    from app.database import get_db_connection
    con = get_db_connection()
    tables = con.execute("SHOW TABLES").fetchall()
    print("Tables:", [t[0] for t in tables])
    
    for table_name in ['intraday_1m', 'historical_data', 'daily_metrics', 'saved_queries', 'strategies']:
        if table_name in [t[0] for t in tables]:
            print(f"\nSchema for {table_name}:")
            res = con.execute(f"DESCRIBE {table_name}").fetchall()
            for row in res:
                print(row)
        else:
            print(f"\nTable {table_name} NOT FOUND")
except Exception as e:
    print(e)
