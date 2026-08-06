"""
PASO 1 — Cuantificar contaminacion por splits en daily_metrics.

Ultimos 24 meses. Universo = mismo filtro de tipo que usa el propio
screener de Edgecute (CS/ADRC/OS), lo que de paso descarta los tickers
de prueba de bolsa (ZVZZT y similares, que ni siquiera existen en la
tabla tickers).

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

# Filtro de fecha obligatorio: 24 meses exactos, ago-2024 a jul-2026
# (hoy es 2026-08-05, agosto 2026 esta incompleto y se deja fuera).
months = [(2024, m) for m in range(8, 13)] + [(2025, m) for m in range(1, 13)] + [(2026, m) for m in range(1, 8)]
paths = [f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={y}/month={m}/*.parquet" for y, m in months]
paths_sql = "[" + ",".join(f"'{p}'" for p in paths) + "]"

con.execute(f"""
    CREATE OR REPLACE TEMP VIEW dm_universo AS
    SELECT dm.ticker, CAST(dm.timestamp AS DATE) AS fecha, dm.prev_close, dm.open, dm.gap_pct
    FROM read_parquet({paths_sql}) dm
    JOIN read_parquet('gs://{GCS_BUCKET}/cold_storage/tickers/*.parquet') t
        ON dm.ticker = t.ticker
    WHERE t.type IN ('CS', 'ADRC', 'OS')
      AND dm.prev_close > 0 AND dm.open > 0
""")

con.execute(f"""
    CREATE OR REPLACE TEMP VIEW dm_flagged AS
    SELECT d.*,
           GREATEST(d.open / d.prev_close, d.prev_close / d.open) AS ratio,
           (GREATEST(d.open / d.prev_close, d.prev_close / d.open) >= 10) AS ratio_sospechoso,
           (sp.ticker IS NOT NULL) AS tiene_split_registrado
    FROM dm_universo d
    LEFT JOIN read_parquet('gs://{GCS_BUCKET}/cold_storage/splits/*.parquet') sp
        ON d.ticker = sp.ticker AND d.fecha = CAST(sp.execution_date AS DATE)
""")

print("=" * 70)
print("1) Dias con ratio open/prev_close > 10x (ultimos 24 meses)")
print("=" * 70)
r1 = con.execute("SELECT COUNT(*) FROM dm_flagged WHERE ratio_sospechoso").fetchone()
total_dias = con.execute("SELECT COUNT(*) FROM dm_flagged").fetchone()[0]
print(f"Total dias en el universo (24m, CS/ADRC/OS): {total_dias:,}")
print(f"Dias con ratio > 10x: {r1[0]:,}")

print()
print("=" * 70)
print("2) De esos, cuantos SI y cuantos NO estan en la tabla splits")
print("=" * 70)
r2 = con.execute("""
    SELECT tiene_split_registrado, COUNT(*)
    FROM dm_flagged WHERE ratio_sospechoso
    GROUP BY 1
""").fetchdf()
print(r2.to_string(index=False))
pct_no = con.execute("""
    SELECT 100.0 * SUM(CASE WHEN NOT tiene_split_registrado THEN 1 ELSE 0 END) / COUNT(*)
    FROM dm_flagged WHERE ratio_sospechoso
""").fetchone()[0]
print(f"\n% sin registrar: {pct_no:.1f}%")

print()
print("=" * 70)
print("3) Contaminacion segun agresividad del filtro de gap_pct")
print("=" * 70)
for umbral in (50, 100, 200):
    row = con.execute(f"""
        SELECT
            COUNT(*) AS dias_seleccionados,
            SUM(CASE WHEN ratio_sospechoso THEN 1 ELSE 0 END) AS sospechosos_split,
            100.0 * SUM(CASE WHEN ratio_sospechoso THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS pct_contaminado,
            SUM(CASE WHEN ratio_sospechoso AND NOT tiene_split_registrado THEN 1 ELSE 0 END) AS sospechosos_sin_registrar
        FROM dm_flagged
        WHERE gap_pct > {umbral}
    """).fetchdf()
    row.insert(0, "umbral_gap_pct", f">{umbral}%")
    print(row.to_string(index=False))
    print()

print("DONE")
