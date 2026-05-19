import os
import pandas as pd
from dotenv import load_dotenv
load_dotenv()

from app.database import get_db_connection

print("Conectando a GCS...")
con = get_db_connection()

print("Cargando gap days desde daily_metrics...")
df = con.execute("""
    SELECT 
        ticker, timestamp, year, month,
        gap_pct, open, close, high, low, volume,
        pm_volume, pm_high, pm_low, rth_volume,
        rth_high, rth_low, rth_run_pct,
        day_return_pct, rth_range_pct,
        pmh_gap_pct, pmh_fade_pct, rth_fade_pct,
        hod_time, lod_time,
        m15_return_pct, m30_return_pct,
        m60_return_pct, m180_return_pct,
        prev_close, eod_volume
    FROM daily_metrics
    WHERE gap_pct >= 20.0
    AND gap_pct <= 500.0
    AND open > 0.10
""").fetchdf()

print(f"Filas: {len(df):,}")

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
