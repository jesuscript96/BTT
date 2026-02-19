import sys
import os
sys.path.append(os.getcwd())
try:
    from app.database import get_db_connection
    con = get_db_connection()
    res = con.execute("DESCRIBE daily_metrics").fetchall()
    print("Schema:")
    for row in res:
        print(row)
except Exception as e:
    print(e)
