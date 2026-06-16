import os
import duckdb
import pandas as pd
import numpy as np
from dotenv import load_dotenv

# Load env variables from backend/.env
load_dotenv('backend/.env')

access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
if access_key and secret:
    con.execute(f"CREATE SECRET gcs_secret (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")

# 1. Fetch intraday 1m data
query_intra = f"""
    SELECT timestamp, open, high, low, close, volume, ticker, CAST(timestamp AS DATE) as date
    FROM read_parquet('gs://{bucket}/cold_storage/intraday_1m/year=2025/month=1/*.parquet', hive_partitioning=true)
    WHERE ticker = 'BNGO'
      AND CAST(timestamp AS DATE) = '2025-01-03'
    ORDER BY timestamp ASC
"""
df_intra = con.execute(query_intra).fetchdf()

# 2. Fetch daily metrics
query_qual = f"""
    SELECT ticker, timestamp, open, close, high, low, pm_high, pm_low, rth_open, rth_high, rth_low, rth_close, gap_pct, pm_volume, prev_close, CAST(timestamp AS DATE) as date
    FROM read_parquet('gs://{bucket}/cold_storage/daily_metrics/**/*.parquet', hive_partitioning=true)
    WHERE ticker = 'BNGO'
      AND CAST(timestamp AS DATE) = '2025-01-03'
"""
df_qual = con.execute(query_qual).fetchdf()
con.close()

# Import the backtest engine
import sys
sys.path.append(os.path.abspath('backend'))
from app.services.backtest_service import run_backtest

# Define the strategy: bias = short, enter short when Bar Close > PM Open
strategy_def = {
    "name": "Test Short PM Open",
    "bias": "short",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": {"name": "PM Open"}
                }
            ]
        }
    },
    "exit_logic": {
        "timeframe": "1m",
        "root_condition": {
            "operator": "AND",
            "conditions": []
        }
    },
    "risk_management": {
        "accept_reentries": False,
        "use_hard_stop": False,
        "use_take_profit": False
    }
}

# Run the backtest
result = run_backtest(
    intraday_df=df_intra,
    qualifying_df=df_qual,
    strategy_def=strategy_def,
    market_sessions=["rth"],
    look_ahead_prevention=True  # Enter on next open
)

print("\n=== BACKTEST RESULTS ===")
trades = result.get("trades", [])
print(f"Total trades executed: {len(trades)}")
for i, t in enumerate(trades):
    print(f"Trade {i+1}:")
    print(f"  Ticker: {t['ticker']}")
    print(f"  Date: {t['date']}")
    print(f"  Direction: {t['direction']}")
    print(f"  Entry Time: {t['entry_time']} | Entry Price: {t['entry_price']}")
    print(f"  Exit Time: {t['exit_time']} | Exit Price: {t['exit_price']}")
    print(f"  PnL: {t['pnl']} | Return %: {t['return_pct']}")
    print(f"  Exit Reason: {t['exit_reason']}")
