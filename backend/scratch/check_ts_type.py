import os
import sys
from dotenv import load_dotenv
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.db.connection import get_connection

def main():
    conn = get_connection()
    from app.db.gcs_cache import _select_intraday_glob_for_month
    path = _select_intraday_glob_for_month(conn, 2024, 1)
    
    sql = f"""
    SELECT timestamp
    FROM read_parquet('{path}', hive_partitioning=true)
    LIMIT 5
    """
    df = conn.execute(sql).fetchdf()
    print("Timestamp column dtype:", df["timestamp"].dtype)
    print("Timestamp values:")
    for val in df["timestamp"]:
        print(repr(val))

if __name__ == "__main__":
    main()
