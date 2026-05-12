from app.database import _establish_connection
import os

con = _establish_connection()
print('=== daily_metrics (GCS view) ===')
try:
    r = con.execute('DESCRIBE daily_metrics').fetchdf()
    print(r.to_string())
except Exception as e:
    print(f'View not created: {e}')
    print()
    print('=== daily_metrics (direct Parquet) ===')
    r = con.execute("""
        DESCRIBE SELECT * FROM read_parquet(
            'gs://strategybuilderbbdd/cold_storage/daily_metrics/year=2026/month=1/*.parquet',
            hive_partitioning=true
        ) LIMIT 0
    """).fetchdf()
    print(r.to_string())

print()
print('=== intraday_1m (direct Parquet) ===')
r = con.execute("""
    DESCRIBE SELECT * FROM read_parquet(
        'gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2026/month=1/*.parquet',
        hive_partitioning=true
    ) LIMIT 0
""").fetchdf()
print(r.to_string())

con.close()
