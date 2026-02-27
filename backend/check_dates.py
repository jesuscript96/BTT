import sqlite3
import pandas as pd
import duckdb
from app.database import get_db_connection

con = get_db_connection(read_only=True)
query = "SELECT timestamp, open FROM intraday_1m WHERE ticker = 'TLIH' LIMIT 5"
df = con.execute(query).fetch_df()
print("Dtype:", df['timestamp'].dtype)
print("First value:", df['timestamp'].iloc[0])
print("Int64 value:", df['timestamp'].astype('int64').iloc[0])
print("Int64 // 10**9:", df['timestamp'].astype('int64').iloc[0] // 10**9)
print("Int64 // 10**6:", df['timestamp'].astype('int64').iloc[0] // 10**6)

# also check unixepoch using standard pandas
print("Pandas standard to unix seconds:", df['timestamp'].astype('int64').iloc[0] // 10**9 if df['timestamp'].dtype == 'datetime64[ns]' else df['timestamp'].astype('int64').iloc[0] // 10**6)
