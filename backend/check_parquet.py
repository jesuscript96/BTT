from app.database import get_db_connection
import os
con = get_db_connection()
bucket = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')
r = con.execute(f"""
    DESCRIBE SELECT * FROM read_parquet(
        'gs://{bucket}/cold_storage/hot_cache/daily_metrics_gaps.parquet'
    ) LIMIT 1
""").fetchdf()
print(r.to_string())
con.close()
