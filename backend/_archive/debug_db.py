from app.database import get_db_connection
import pandas as pd

try:
    con = get_db_connection()
    print("Connected!")
    
    # Check tables
    tables = con.execute("SHOW TABLES").fetchall()
    print(f"Tables: {[t[0] for t in tables]}")
    
    # Query sample
    df = con.execute("SELECT * FROM intraday_1m LIMIT 5").fetch_df()
    print("\nSample Data:")
    print(df)
    
    # Query for a specific time to see format
    df_time = con.execute("SELECT timestamp FROM intraday_1m WHERE timestamp::VARCHAR LIKE '%08:30:00' LIMIT 5").fetch_df()
    print("\n08:30 Sample:")
    print(df_time)
    
except Exception as e:
    print(f"Error: {e}")
finally:
    if 'con' in locals():
        con.close()
