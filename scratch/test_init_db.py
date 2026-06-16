from app.init_db import init_db
from app.database import get_db_connection

# Initialize database views
init_db()

con = get_db_connection()
try:
    df = con.execute("""
        SELECT * EXCLUDE (pmh_gap_pct), 
               ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) as pmh_gap_pct 
        FROM daily_metrics 
        LIMIT 1
    """).fetch_df()
    print("Success! Columns:")
    print(df.columns.tolist())
    print("pmh_gap_pct value:", df['pmh_gap_pct'].iloc[0])
except Exception as e:
    print("Error:", e)
con.close()
