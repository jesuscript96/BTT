import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.db.connection import get_connection

def main():
    conn = get_connection()
    # Let's inspect a single day of intraday data for a ticker
    # We can glob in gs://strategybuilderbbdd/cold_storage/intraday_1m_optimized/year=2024/month=01/*.parquet
    from app.db.gcs_cache import _select_intraday_glob_for_month
    path = _select_intraday_glob_for_month(conn, 2024, 1)
    
    print(f"Reading intraday sample from resolved path: {path}")
    try:
        sql = f"""
        SELECT ticker, date, timestamp, open, high, low, close, volume
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE ticker = 'SAVE' AND date = '2024-01-19'
        ORDER BY timestamp
        """
        df = conn.execute(sql).fetchdf()
        print(f"Total rows fetched: {len(df)}")
        if df.empty:
            print("No rows fetched!")
            return
            
        print("First 10 rows:")
        print(df.head(10))
        
        print("\nLast 10 rows:")
        print(df.tail(10))
        
        # Check time ranges (EST)
        df['time'] = pd.to_datetime(df['timestamp']).dt.time
        print("\nTime range of timestamps (UTC or EST):")
        print("Min time:", df['time'].min())
        print("Max time:", df['time'].max())
        
        # Check RTH session vs Pre vs Post
        c_times = pd.to_datetime(df['timestamp']).dt.time
        pre = df[(c_times >= pd.Timestamp("04:00").time()) & (c_times < pd.Timestamp("09:30").time())]
        rth = df[(c_times >= pd.Timestamp("09:30").time()) & (c_times < pd.Timestamp("16:00").time())]
        post = df[(c_times >= pd.Timestamp("16:00").time()) & (c_times < pd.Timestamp("20:00").time())]
        
        print(f"\nPre-market bars count (04:00 - 09:30): {len(pre)}")
        print(f"RTH bars count (09:30 - 16:00): {len(rth)}")
        print(f"Post-market bars count (16:00 - 20:00): {len(post)}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
