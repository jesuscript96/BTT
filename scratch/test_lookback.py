import sys
import os
sys.path.append(os.path.abspath('backend'))

from app.database import get_db_connection
from app.init_db import init_db
import pandas as pd
import numpy as np

# Initialize
init_db()

con = get_db_connection()

ticker = 'GFAI'
try:
    df_daily = con.execute(f"""
        SELECT CAST("timestamp" AS DATE) as date, rth_high, rth_low 
        FROM daily_metrics 
        WHERE ticker = '{ticker}' 
        ORDER BY "timestamp"
    """).fetchdf()
    print("Columns:", df_daily.columns.tolist())
    print("Rows:", len(df_daily))
    print(df_daily.head(5))
except Exception as e:
    print("Error:", e)

con.close()
