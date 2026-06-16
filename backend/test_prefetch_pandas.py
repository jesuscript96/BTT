from app.database import get_db_connection
import time
import pandas as pd

con = get_db_connection()
try:
    print("Fetching all tickers from tickers view first to simulate a large list of tickers...")
    tickers = con.execute("SELECT DISTINCT ticker FROM tickers").fetchdf()["ticker"].tolist()
    print(f"Total tickers: {len(tickers)}")
    
    # We will test prefetching for a subset of 2500 tickers
    tickers_to_fetch = tickers[:2500]
    print(f"Testing prefetch for {len(tickers_to_fetch)} tickers...")
    
    t0 = time.time()
    # Query the whole table
    df_all = con.execute("""
        SELECT ticker, CAST("timestamp" AS DATE) as date, rth_high, rth_low 
        FROM daily_metrics 
        ORDER BY ticker, "timestamp"
    """).fetchdf()
    t1 = time.time()
    print(f"Fetched {len(df_all):,} rows from daily_metrics in {t1-t0:.2f}s")
    
    # Convert date to string format
    df_all["date"] = pd.to_datetime(df_all["date"]).dt.strftime("%Y-%m-%d")
    t2 = time.time()
    print(f"Converted dates in {t2-t1:.2f}s")
    
    # Filter in Pandas
    df_filtered = df_all[df_all["ticker"].isin(tickers_to_fetch)]
    t3 = time.time()
    print(f"Filtered to {len(df_filtered):,} rows in {t3-t2:.2f}s")
    
    # Group and build cache dict
    cache = {}
    for ticker_symbol, group in df_filtered.groupby("ticker"):
        group_indexed = group.set_index("date")
        group_indexed = group_indexed[~group_indexed.index.duplicated(keep='first')]
        cache[ticker_symbol] = group_indexed
    t4 = time.time()
    print(f"Grouped and cached {len(cache)} tickers in {t4-t3:.2f}s")
    print(f"Total execution time: {t4-t0:.2f}s")
except Exception as e:
    print("Error:", e)
