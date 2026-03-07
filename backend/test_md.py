import os
from dotenv import load_dotenv
import duckdb

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")
print("Token prefix:", token[:10] if token else "None")

try:
    conn_str = f"md:?motherduck_token={token}"
    con = duckdb.connect(conn_str)
    print("✅ Connected to MotherDuck")
    res = con.execute("SELECT count(*) FROM saved_queries").fetchone()
    print("saved_queries count:", res[0])
except Exception as e:
    print("❌ Error:", e)
