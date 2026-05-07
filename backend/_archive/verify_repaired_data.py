import duckdb
import os
from dotenv import load_dotenv
from app.database import get_db_connection

load_dotenv()

print("Inspecting Repaired NVDA Data...")
con = get_db_connection()
df = con.execute("""
    SELECT 
        date, 
        ticker, 
        rth_run_pct, 
        pm_high, 
        pm_volume, 
        pmh_fade_to_open_pct
    FROM daily_metrics 
    WHERE ticker = 'NVDA' 
    ORDER BY date DESC 
    LIMIT 5
""").fetch_df()
print(df)
con.close()
