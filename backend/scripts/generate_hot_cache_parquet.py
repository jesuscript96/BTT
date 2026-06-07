import os
import pandas as pd
import duckdb
from dotenv import load_dotenv
load_dotenv()

GCS_BUCKET = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
GCS_HMAC_KEY = os.getenv("GCS_HMAC_KEY", "")
GCS_HMAC_SECRET = os.getenv("GCS_HMAC_SECRET", "")

print("Conectando a GCS...")
con = duckdb.connect(":memory:")
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(f"SET s3_access_key_id='{GCS_HMAC_KEY}';")
con.execute(f"SET s3_secret_access_key='{GCS_HMAC_SECRET}';")
con.execute("SET s3_endpoint='storage.googleapis.com';")
con.execute("SET s3_region='us-east-1';")
con.execute("SET s3_url_style='path';")

daily_path = f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/*/*/*.parquet"

print(f"Cargando gap days desde {daily_path}...")
t_start = pd.Timestamp.now()
df = con.execute(f"""
    WITH runner_and_gap_days AS (
        SELECT DISTINCT ticker, CAST(timestamp AS DATE) as anchor_date
        FROM read_parquet('{daily_path}', hive_partitioning=true)
        WHERE (
            (gap_pct >= 10.0 AND gap_pct <= 500.0)
            OR
            (pm_high > 0 AND prev_close > 0
             AND ((pm_high - prev_close) / prev_close * 100) >= 20)
        )
        AND open > 0.10
    ),
    all_trading_days AS (
        SELECT DISTINCT ticker, CAST(timestamp AS DATE) as date
        FROM read_parquet('{daily_path}', hive_partitioning=true)
    ),
    expanded_dates AS (
        SELECT DISTINCT a.ticker, a.date
        FROM all_trading_days a
        INNER JOIN runner_and_gap_days r
            ON a.ticker = r.ticker
            AND a.date BETWEEN r.anchor_date - INTERVAL 2 DAY
                           AND r.anchor_date + INTERVAL 2 DAY
    )
    SELECT
        d.ticker, d.timestamp, d.year, d.month,
        d.gap_pct, d.open, d.close, d.high, d.low, d.volume,
        d.pm_volume, d.pm_high, d.pm_low, d.pm_high_time, d.pm_low_time,
        d.rth_volume, d.rth_open, d.rth_high, d.rth_low, d.rth_close,
        d.rth_run_pct, d.day_return_pct, d.rth_range_pct,
        d.pmh_gap_pct, d.pmh_fade_pct, d.rth_fade_pct,
        d.hod_time, d.lod_time,
        d.m15_return_pct, d.m30_return_pct, d.m60_return_pct, d.m180_return_pct,
        d.close_1559, d.last_close, d.prev_close, d.eod_volume,
        d.transactions
    FROM read_parquet('{daily_path}', hive_partitioning=true) d
    INNER JOIN expanded_dates e
        ON d.ticker = e.ticker
        AND CAST(d.timestamp AS DATE) = e.date
    WHERE d.open > 0.10
""").fetchdf()
t_elapsed = (pd.Timestamp.now() - t_start).total_seconds()

print(f"Filas: {len(df):,}")
mem_mb = df.memory_usage(deep=True).sum() / 1024 / 1024
print(f"Tamaño: {mem_mb:.1f} MB, Tiempo query: {t_elapsed:.1f}s")

# Optimizar memoria
for col in df.select_dtypes(include=['float64']).columns:
    df[col] = df[col].astype('float32')
if 'ticker' in df.columns:
    df['ticker'] = df['ticker'].astype('category')

# Guardar local primero
local_path = "hot_cache_daily_gaps.parquet"
df.to_parquet(local_path, index=False)
print(f"Guardado local: {local_path}")

# Subir a GCS
from google.cloud import storage
import tempfile

gcs_key_content = os.getenv("GCS_KEY_CONTENT", "")
gcs_key_b64 = os.getenv("GCS_KEY_B64", "")
gcs_key_file = os.getenv("GCS_KEY_FILE", "")
bucket_name = os.getenv("GCS_BUCKET", "strategybuilderbbdd")

if gcs_key_content:
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(gcs_key_content)
        tmp_key_path = f.name
    client = storage.Client.from_service_account_json(tmp_key_path)
    os.unlink(tmp_key_path)
elif gcs_key_b64:
    import base64
    key_data = base64.b64decode(gcs_key_b64).decode()
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(key_data)
        tmp_key_path = f.name
    client = storage.Client.from_service_account_json(tmp_key_path)
    os.unlink(tmp_key_path)
elif gcs_key_file and os.path.exists(gcs_key_file):
    client = storage.Client.from_service_account_json(gcs_key_file)
else:
    client = storage.Client()
bucket = client.bucket(bucket_name)
blob = bucket.blob("cold_storage/hot_cache/daily_metrics_gaps.parquet")
blob.upload_from_filename(local_path)
print(f"Subido a gs://{bucket_name}/cold_storage/hot_cache/daily_metrics_gaps.parquet")
os.remove(local_path)
print("Listo.")
