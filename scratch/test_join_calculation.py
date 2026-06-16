import sys
import os
from dotenv import load_dotenv

# Load env before any imports from app
load_dotenv('backend/.env')

sys.path.append(os.path.abspath('backend'))

from app.db.connection import get_connection

con = get_connection()

try:
    # 1. Let's find some qualified tickers and dates from GCS daily_metrics
    print("Finding qualified ticker-date pairs from GCS...")
    pairs = con.execute("""
        SELECT ticker, CAST(timestamp AS DATE) as date, gap_pct 
        FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
        WHERE gap_pct >= 20.0 
        ORDER BY timestamp DESC, gap_pct DESC 
        LIMIT 10
    """).fetchdf()
    print(pairs)
    
    if pairs.empty:
        print("No qualified pairs found.")
        sys.exit(0)
        
    # Construct a query to get intraday data for these pairs on their specific match dates
    # We will join intraday_1m with a VALUES clause containing these pairs
    values_str = ", ".join([f"('{r['ticker']}', '{r['date']}'::DATE)" for _, r in pairs.iterrows()])
    
    query = f"""
        WITH screen_res AS (
            SELECT * FROM (
                VALUES {values_str}
            ) AS t(ticker, date)
        ),
        daily_opens AS (
            SELECT i.ticker, i.date, i.close as day_open
            FROM (
                SELECT i.ticker, i.date, i.close,
                       ROW_NUMBER() OVER (PARTITION BY i.ticker, i.date ORDER BY i.timestamp ASC) as rn
                FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true) i
                JOIN screen_res s ON i.ticker = s.ticker AND i.date = s.date
                WHERE i.timestamp >= CAST(i.date || ' 09:30:00' AS TIMESTAMP)
            ) i
            WHERE rn = 1
        ),
        joined_intraday AS (
            SELECT i.timestamp, i.ticker, i.date, i.close, d.day_open,
                   ((i.close - d.day_open) / NULLIF(d.day_open, 0) * 100) as pct_change
            FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true) i
            JOIN screen_res s ON i.ticker = s.ticker AND i.date = s.date
            JOIN daily_opens d ON i.ticker = d.ticker AND i.date = d.date
            WHERE d.day_open > 0
        )
        SELECT strftime(timestamp, '%H:%M') as minute,
               COUNT(DISTINCT ticker) as num_tickers,
               AVG(pct_change) as avg_change,
               QUANTILE_CONT(pct_change, 0.5) as median_change
        FROM joined_intraday
        GROUP BY 1 ORDER BY 1
    """
    
    res = con.execute(query).fetchdf()
    print("\n--- Intraday Aggregation Results (first 15 rows) ---")
    print(res.head(15))
    print("\n--- Intraday Aggregation Results (last 15 rows) ---")
    print(res.tail(15))
    
except Exception as e:
    print(f"Error: {e}")
finally:
    con.close()
