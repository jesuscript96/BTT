"""
PASO 3 -- Detector de splits por redondez del ratio open/prev_close,
en vez del umbral fijo ratio >= 10 usado en paso1_contaminacion.py.

Hipotesis del usuario: el umbral >=10 solo pilla splits 1:10 o mas
agresivos. Un 1:5 (ratio=5) o un 1:8 (ratio=8) pasan limpios como si
fueran gaps reales, así que los porcentajes de contaminacion de
paso1 (25.6% / 42.7% / 60.9% a gap>50/100/200%) estan contados por lo
bajo.

Detector nuevo: ratio > 1.8 Y a menos de 1% de un entero. Un split
1:N real produce ratio muy cercano a N.000; un gap real cae en
valores "sucios" tipo 2.87 o 3.14.

Mismo universo y mismo periodo que paso1 (24 meses, ago-2024 a
jul-2026, tickers CS/ADRC/OS) para que las comparaciones sean
homogeneas. Ratio SIMETRICO (GREATEST(open/prev_close,
prev_close/open)), igual que paso1 -- no solo la direccion alcista --
para poder comparar manzanas con manzanas contra el metodo antiguo.

Solo lectura. No modifica nada.
"""

import os

import duckdb
import pandas as pd
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
    SELECT dm.ticker, CAST(dm.timestamp AS DATE) AS fecha, dm.prev_close, dm.open, dm.gap_pct,
           dm.volume, dm.eod_volume
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
           ROUND(GREATEST(d.open / d.prev_close, d.prev_close / d.open)) AS nearest_int,
           ABS(GREATEST(d.open / d.prev_close, d.prev_close / d.open)
               - ROUND(GREATEST(d.open / d.prev_close, d.prev_close / d.open)))
               / ROUND(GREATEST(d.open / d.prev_close, d.prev_close / d.open)) AS pct_diff_int,
           (sp.ticker IS NOT NULL) AS tiene_split_registrado,
           LAG(d.volume) OVER (PARTITION BY d.ticker ORDER BY d.fecha) AS volume_dia_anterior,
           LAG(d.eod_volume) OVER (PARTITION BY d.ticker ORDER BY d.fecha) AS eod_volume_dia_anterior
    FROM dm_universo d
    LEFT JOIN read_parquet('gs://{GCS_BUCKET}/cold_storage/splits/*.parquet') sp
        ON d.ticker = sp.ticker AND d.fecha = CAST(sp.execution_date AS DATE)
""")

con.execute("""
    CREATE OR REPLACE TEMP VIEW dm_scored AS
    SELECT *,
           (ratio >= 10) AS old_sospechoso,
           (ratio > 1.8 AND nearest_int >= 2 AND pct_diff_int <= 0.01) AS new_sospechoso
    FROM dm_flagged
""")

total_dias = con.execute("SELECT COUNT(*) FROM dm_scored").fetchone()[0]
print("=" * 70)
print(f"Universo: {total_dias:,} dias-ticker (24m, CS/ADRC/OS, prev_close>0, open>0)")
print("=" * 70)

print()
print("=" * 70)
print("1) Dias con ratio > 1.8 Y a <1% de un entero — distribucion por entero")
print("=" * 70)
r1 = con.execute("""
    SELECT nearest_int, COUNT(*) AS dias
    FROM dm_scored WHERE new_sospechoso
    GROUP BY 1 ORDER BY 1
""").fetchdf()
print(r1.to_string(index=False))
total_new = int(r1["dias"].sum()) if not r1.empty else 0
print(f"\nTotal detectados por redondez: {total_new:,}")

print()
print("=" * 70)
print("2) De esos, cuantos SI y cuantos NO estan en la tabla splits")
print("=" * 70)
r2 = con.execute("""
    SELECT tiene_split_registrado, COUNT(*) AS dias
    FROM dm_scored WHERE new_sospechoso
    GROUP BY 1
""").fetchdf()
print(r2.to_string(index=False))

print()
print("=" * 70)
print("3) Comparacion contra el metodo antiguo (ratio >= 10)")
print("=" * 70)
r3 = con.execute("""
    SELECT
        SUM(CASE WHEN old_sospechoso THEN 1 ELSE 0 END) AS detectados_metodo_antiguo,
        SUM(CASE WHEN new_sospechoso THEN 1 ELSE 0 END) AS detectados_metodo_nuevo,
        SUM(CASE WHEN new_sospechoso AND NOT old_sospechoso THEN 1 ELSE 0 END) AS nuevos_no_detectados_antes,
        SUM(CASE WHEN old_sospechoso AND NOT new_sospechoso THEN 1 ELSE 0 END) AS antiguos_perdidos_por_el_nuevo,
        SUM(CASE WHEN old_sospechoso AND new_sospechoso THEN 1 ELSE 0 END) AS interseccion
    FROM dm_scored
""").fetchdf()
print(r3.to_string(index=False))

print()
print("Desglose de los 'nuevos no detectados antes' por entero (deberian ser < 10x):")
r3b = con.execute("""
    SELECT nearest_int, COUNT(*) AS dias
    FROM dm_scored WHERE new_sospechoso AND NOT old_sospechoso
    GROUP BY 1 ORDER BY 1
""").fetchdf()
print(r3b.to_string(index=False))

print()
print("=" * 70)
print("4) Riesgo de falsos positivos: detectados por redondez SIN registro en splits")
print("=" * 70)
r4count = con.execute("""
    SELECT COUNT(*) FROM dm_scored WHERE new_sospechoso AND NOT tiene_split_registrado
""").fetchone()[0]
print(f"Total sin registrar: {r4count:,} de {total_new:,} detectados")
print("\n5 ejemplos MAS AMBIGUOS (mas cerca del limite del 1%, los mas dificiles de juzgar):")
r4 = con.execute("""
    SELECT ticker, fecha, prev_close, open, ROUND(ratio, 4) AS ratio,
           nearest_int, ROUND(pct_diff_int * 100, 3) AS pct_diff_pct,
           ROUND(gap_pct, 1) AS gap_pct
    FROM dm_scored
    WHERE new_sospechoso AND NOT tiene_split_registrado
    ORDER BY pct_diff_int DESC
    LIMIT 5
""").fetchdf()
print(r4.to_string(index=False))

print()
print("=" * 70)
print("5) Señal de volumen: ¿el volumen cae proporcionalmente al ratio?")
print("=" * 70)
print("Comparando volume_dia / volume_dia_anterior contra 1/ratio esperado,")
print("para casos CON split registrado vs SIN registrar (ambos del detector nuevo).")
r5 = con.execute("""
    SELECT
        tiene_split_registrado,
        COUNT(*) AS n,
        COUNT(volume_dia_anterior) AS n_con_dia_anterior,
        ROUND(AVG(volume / NULLIF(volume_dia_anterior, 0)), 3) AS avg_ratio_volumen_dia_vs_anterior,
        ROUND(MEDIAN(volume / NULLIF(volume_dia_anterior, 0)), 3) AS mediana_ratio_volumen,
        ROUND(AVG(1.0 / ratio), 3) AS caida_esperada_1_sobre_ratio
    FROM dm_scored
    WHERE new_sospechoso AND volume_dia_anterior IS NOT NULL AND volume_dia_anterior > 0
    GROUP BY 1
""").fetchdf()
print(r5.to_string(index=False))

print()
print("=" * 70)
print("6) Contaminacion recalculada con el detector nuevo, por umbral de gap_pct")
print("=" * 70)
print("(comparando lado a lado el metodo antiguo -- paso1 -- con el nuevo)")
for umbral in (50, 100, 200):
    row = con.execute(f"""
        SELECT
            COUNT(*) AS dias_seleccionados,
            SUM(CASE WHEN old_sospechoso THEN 1 ELSE 0 END) AS sosp_ANTIGUO,
            100.0 * SUM(CASE WHEN old_sospechoso THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS pct_ANTIGUO,
            SUM(CASE WHEN new_sospechoso THEN 1 ELSE 0 END) AS sosp_NUEVO,
            100.0 * SUM(CASE WHEN new_sospechoso THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS pct_NUEVO,
            SUM(CASE WHEN new_sospechoso AND NOT tiene_split_registrado THEN 1 ELSE 0 END) AS nuevo_sin_registrar
        FROM dm_scored
        WHERE gap_pct > {umbral}
    """).fetchdf()
    row.insert(0, "umbral_gap_pct", f">{umbral}%")
    print(row.to_string(index=False))
    print()

print("DONE")
