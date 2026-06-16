from app.database import get_db_connection
import time

con = get_db_connection()
try:
    # A few sample tickers
    tickers = ["AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL"]
    tickers_str = ", ".join(f"'{t}'" for t in tickers)
    
    print("Testing query on optimized intraday path (2023-1)...")
    opt_path = "gs://strategybuilderbbdd/cold_storage/intraday_1m_optimized/year=2023/month=1/*.parquet"
    t0 = time.time()
    df_opt = con.execute(f"""
        SELECT ticker, date, timestamp, open, high, low, close, volume
        FROM read_parquet('{opt_path}', hive_partitioning=true)
        WHERE year = 2023 AND month = 1 AND ticker IN ({tickers_str})
    """).fetchdf()
    print(f"Fetched {len(df_opt)} rows in {time.time()-t0:.2f}s")
    
    print("\nTesting query on raw intraday path (2023-1)...")
    raw_path = "gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2023/month=1/*.parquet"
    t0 = time.time()
    df_raw = con.execute(f"""
        SELECT ticker, date, timestamp, open, high, low, close, volume
        FROM read_parquet('{raw_path}', hive_partitioning=true)
        WHERE year = 2023 AND month = 1 AND ticker IN ({tickers_str})
    """).fetchdf()
    print(f"Fetched {len(df_raw)} rows in {time.time()-t0:.2f}s")
    
except Exception as e:
    print("Error:", e)
