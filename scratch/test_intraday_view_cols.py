import os
import sys
import duckdb
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(env_path)

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
con.execute(f"CREATE SECRET gcs_sec (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")

print("--- VIEW DEFINITION 1: */*/*.parquet ---")
try:
    con.execute("""
        CREATE OR REPLACE VIEW intraday_1m_3 AS 
        SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true)
    """)
    cols = con.execute("DESCRIBE intraday_1m_3").fetchall()
    print("Columns in 3-glob view:", [c[0] for c in cols])
    cnt = con.execute("SELECT COUNT(*) FROM intraday_1m_3 WHERE year = 2024 AND month = 3").fetchone()[0]
    print("Count for year=2024, month=3:", cnt)
except Exception as e:
    print("Error with 3-glob:", e)

print("--- VIEW DEFINITION 2: */*/*/*.parquet ---")
try:
    con.execute("""
        CREATE OR REPLACE VIEW intraday_1m_4 AS 
        SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*/*.parquet', hive_partitioning=true)
    """)
    cols = con.execute("DESCRIBE intraday_1m_4").fetchall()
    print("Columns in 4-glob view:", [c[0] for c in cols])
    cnt = con.execute("SELECT COUNT(*) FROM intraday_1m_4 WHERE year = 2024 AND month = 3").fetchone()[0]
    print("Count for year=2024, month=3:", cnt)
except Exception as e:
    print("Error with 4-glob:", e)

con.close()
