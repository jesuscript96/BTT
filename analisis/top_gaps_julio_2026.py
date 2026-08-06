"""
Prueba de acceso a los datos de Edgecute desde FUERA de la app.

Qué hace: devuelve los 20 tickers con mayor gap_pct en julio de 2026,
excluyendo los días que coinciden con un split (para no contar como
"gap" lo que en realidad es un split sin ajustar).

Solo lectura. No modifica nada en GCS ni en la app.
"""

import os

import duckdb
from dotenv import load_dotenv

# Reutilizamos las credenciales que ya existen en backend/.env — de solo
# lectura, y así no duplicamos el secreto en un segundo fichero.
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(ENV_PATH)

GCS_BUCKET = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
GCS_HMAC_KEY = os.getenv("GCS_HMAC_KEY")
GCS_HMAC_SECRET = os.getenv("GCS_HMAC_SECRET")

if not GCS_HMAC_KEY or not GCS_HMAC_SECRET:
    raise SystemExit(f"No encontré las credenciales de GCS en {ENV_PATH}")

# Conexión DuckDB "en memoria" (no crea ningún fichero local) con el
# módulo httpfs, que es el que sabe leer ficheros gs:// por HTTP.
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(
    f"CREATE SECRET gcs_secret (TYPE GCS, KEY_ID '{GCS_HMAC_KEY}', SECRET '{GCS_HMAC_SECRET}');"
)

# Filtro de fecha OBLIGATORIO: apuntamos directo a la carpeta de julio
# 2026 (year=2026/month=7). Así DuckDB solo abre esos ficheros, nunca
# el histórico completo — nada de escaneos sin filtro.
QUERY = f"""
    SELECT
        dm.ticker,
        CAST(dm.timestamp AS DATE) AS fecha,
        dm.gap_pct,
        dm.prev_close,
        dm.open
    FROM read_parquet(
        'gs://{GCS_BUCKET}/cold_storage/daily_metrics/year=2026/month=7/*.parquet'
    ) AS dm
    LEFT JOIN read_parquet(
        'gs://{GCS_BUCKET}/cold_storage/splits/*.parquet'
    ) AS sp
        ON dm.ticker = sp.ticker
        AND CAST(dm.timestamp AS DATE) = CAST(sp.execution_date AS DATE)
    WHERE sp.ticker IS NULL          -- descarta días que coinciden con un split
      AND dm.gap_pct IS NOT NULL
    ORDER BY dm.gap_pct DESC
    LIMIT 20
"""

df = con.execute(QUERY).fetchdf()

print("\nTop 20 gaps - julio 2026 (excluyendo dias de split)\n")
print(df.to_string(index=False))
