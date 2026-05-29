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
    SELECT 
        ticker, timestamp, year, month,
        gap_pct, open, close, high, low, volume,
        pm_volume, pm_high, pm_low, pm_high_time, pm_low_time,
        rth_volume, rth_open, rth_high, rth_low, rth_close,
        rth_run_pct, day_return_pct, rth_range_pct,
        pmh_gap_pct, pmh_fade_pct, rth_fade_pct,
        hod_time, lod_time,
        m15_return_pct, m30_return_pct, m60_return_pct, m180_return_pct,
        close_1559, last_close, prev_close, eod_volume,
        transactions
    FROM read_parquet('{daily_path}', hive_partitioning=true)
    WHERE (
        (gap_pct >= 20.0 AND gap_pct <= 500.0)
        OR
        (pm_high > 0 AND prev_close > 0
         AND ((pm_high - prev_close) / prev_close * 100) >= 20)
    )
    AND open > 0.10
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
key_file = os.getenv("GCS_KEY_FILE", "gcs-key.json")
bucket_name = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
client = storage.Client.from_service_account_json(key_file)
bucket = client.bucket(bucket_name)
blob = bucket.blob("cold_storage/hot_cache/daily_metrics_gaps.parquet")
blob.upload_from_filename(local_path)
print(f"Subido a gs://{bucket_name}/cold_storage/hot_cache/daily_metrics_gaps.parquet")
os.remove(local_path)
print("Listo.")
