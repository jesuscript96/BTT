"""
Lista de los N casos con ratio open/prev_close >= 10 que NO estan en
la tabla splits, ultimos 24 meses, universo CS/ADRC/OS, excluyendo
tickers de prueba (ZVZZT, ZWZZT).

Solo lectura. No modifica nada.
"""

import os

import duckdb
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(ENV_PATH)

GCS_BUCKET = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(
    f"CREATE SECRET gcs_secret (TYPE GCS, KEY_ID '{os.getenv('GCS_HMAC_KEY')}', "
    f"SECRET '{os.getenv('GCS_HMAC_SECRET')}');"
)
con.execute("SET memory_limit='6GB';")

months = [(2024, m) for m in range(8, 13)] + [(2025, m) for m in range(1, 13)] + [(2026, m) for m in range(1, 8)]
paths = [f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={y}/month={m}/*.parquet" for y, m in months]
paths_sql = "[" + ",".join(f"'{p}'" for p in paths) + "]"

con.execute(f"""
    CREATE OR REPLACE TEMP VIEW dm_universo AS
    SELECT dm.ticker, CAST(dm.timestamp AS DATE) AS fecha, dm.prev_close, dm.open
    FROM read_parquet({paths_sql}) dm
    JOIN read_parquet('gs://{GCS_BUCKET}/cold_storage/tickers/*.parquet') t
        ON dm.ticker = t.ticker
    WHERE t.type IN ('CS', 'ADRC', 'OS')
      AND dm.prev_close > 0 AND dm.open > 0
      AND dm.ticker NOT IN ('ZVZZT', 'ZWZZT')
""")

df = con.execute(f"""
    SELECT
        d.ticker,
        d.fecha,
        d.prev_close,
        d.open,
        GREATEST(d.open / d.prev_close, d.prev_close / d.open) AS ratio
    FROM dm_universo d
    LEFT JOIN read_parquet('gs://{GCS_BUCKET}/cold_storage/splits/*.parquet') sp
        ON d.ticker = sp.ticker AND d.fecha = CAST(sp.execution_date AS DATE)
    WHERE GREATEST(d.open / d.prev_close, d.prev_close / d.open) >= 10
      AND sp.ticker IS NULL
    ORDER BY ratio DESC
""").fetchdf()

print(f"TOTAL_FILAS={len(df)}")

import math

def cerca_redondo(ratio, umbral_pct=5.0):
    candidatos = [10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 150, 200, 250, 300, 400, 500, 1000]
    mejor = min(candidatos, key=lambda c: abs(ratio - c))
    dev_pct = abs(ratio - mejor) / mejor * 100
    if dev_pct <= umbral_pct:
        return mejor, dev_pct
    return None, None

rows = []
for _, r in df.iterrows():
    redondo, dev = cerca_redondo(r["ratio"])
    rows.append({
        "ticker": r["ticker"],
        "fecha": r["fecha"],
        "prev_close": r["prev_close"],
        "open": r["open"],
        "ratio": r["ratio"],
        "ratio_redondeado": round(r["ratio"]),
        "cerca_de_redondo": redondo,
        "desviacion_pct": dev,
    })

import pandas as pd
out = pd.DataFrame(rows)
out.to_csv(os.path.join(os.path.dirname(__file__), "lista_106_sin_registrar.csv"), index=False)
print(out.to_string(index=False))
print("DONE")
