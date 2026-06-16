import sys
import os
import json

# Add backend directory to path
sys.path.append(r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend")

# Set DB_PROVIDER to gcs or local to match environment
os.environ["DB_PROVIDER"] = "gcs" # or "local", let's check what's in uvicorn's environment or .env

from app.database import get_user_db_connection, get_user_db_lock
from app.services.query_service import build_screener_query
import pandas as pd
from uuid import uuid4

# Setup test payload
# When user creates a dataset, they send:
# name, filters
# Let's inspect the filters sent by InlineDatasetBuilder
filters = {
    "date_from": "2024-01-01",
    "date_to": "2024-12-31",
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
    "min_gap_pct": None,
    "max_gap_pct": None,
    "min_pm_volume": None,
    "min_rth_volume": None,
    "rules": [
        {
            "metric": "Close Price",
            "operator": "GREATER_THAN_OR_EQUAL",
            "valueType": "static",
            "value": "10.0"
        }
    ]
}

query_id = str(uuid4())
name = "Test Dataset"

con = get_user_db_connection()
try:
    print("Checking if we can save query metadata...")
    con.execute(
        "INSERT INTO saved_queries (id, name, filters) VALUES (?, ?, ?)",
        (query_id, name, json.dumps(filters))
    )
    print("Saved query metadata successfully.")
    
    con.execute(
        "INSERT INTO datasets (id, name) VALUES (?, ?)",
        (query_id, name)
      )
    print("Saved dataset metadata successfully.")
    
    # Run the SQL generator
    _, params, _, _, _, where_m_stats = build_screener_query(filters, limit=100000)
    print("Screener query built. params:", params)
    print("where_m_stats:", where_m_stats)
    
    subquery_lagged = """
    (
        SELECT *,
               LEAD(rth_close, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_close_1,
               LEAD(pmh_gap_pct, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_pmh_gap_pct_1,
               LEAD(pm_volume, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_pm_volume_1,
               LEAD(gap_pct, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_gap_pct_1,
               LEAD(rth_volume, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_volume_1,
               LEAD(rth_range_pct, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_range_pct_1,
               
               LEAD(rth_close, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_close_2,
               LEAD(pmh_gap_pct, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_pmh_gap_pct_2,
               LEAD(pm_volume, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_pm_volume_2,
               LEAD(gap_pct, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_gap_pct_2,
               LEAD(rth_volume, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_volume_2,
               LEAD(rth_range_pct, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_range_pct_2
        FROM daily_metrics
    ) dm_lagged
    """
    
    insert_sql = f"""
        INSERT INTO dataset_pairs (dataset_id, ticker, date)
        SELECT ? as dataset_id, ticker, CAST(timestamp AS DATE) as date
        FROM {subquery_lagged}
        WHERE {where_m_stats.replace('daily_metrics.', 'dm_lagged.')}
    """
    
    print("Executing insert_sql...")
    con.execute(insert_sql, [query_id] + params)
    print("Saved combinations successfully!")
    
    # Check what is in dataset_pairs
    df = con.execute("SELECT * FROM dataset_pairs WHERE dataset_id = ?", [query_id]).fetchdf()
    print("Inserted rows in dataset_pairs:")
    print(df)
    
except Exception as e:
    print(f"FAILED with error: {e}")
finally:
    # rollback
    con.execute("ROLLBACK;")
    con.close()
