"""Construye `daily_overhead`: la tabla diaria que alimenta «Overhead last X days».

QUE ES
------
Una tabla APARTE, generada, que NO forma parte del lago ni lo modifica. Se lee
sola, con `read_parquet` de disco, y solo cuando una estrategia usa el
indicador. Si no existe, el indicador devuelve NaN y avisa: nada mas del
backtester depende de ella.

POR QUE APARTE (decision de Jaume, 7-sep-2026)
----------------------------------------------
`daily_metrics` la usan el screener, los filtros de universo y
`daily_metrics_windowed`. Tocarla para anadirle columnas arriesga el "historico
rapido". Esto es un fichero nuevo que no pisa nada.

QUE LLEVA
---------
Velas DIARIAS de sesion regular (09:30-16:00): sin premercado y sin after.
O/H/L/C y volumen, mas el FACTOR DE SPLIT ACUMULADO.

  Aviso aceptado: el techo de un runner que hizo su pico a las 08:00 en
  premercado NO esta aqui. Es el maximo que se ve en un grafico diario.

POR QUE EL FACTOR Y NO EL PRECIO YA AJUSTADO
--------------------------------------------
El lago guarda precios CRUDOS. "Ajustado" siempre es relativo a una fecha: si
guardaramos los precios ajustados a hoy, un backtest de febrero de 2025
compararia contra la escala de 2026. Guardando `cum_split` el ajuste se hace al
LEER, relativo al dia del trade:

    precio_comparable = precio[P] * cum_split[T] / cum_split[P]
    volumen_comparable = volumen[P] / (cum_split[T] / cum_split[P])

El volumen se ajusta TAMBIEN, dividiendo: tras un contrasplit 20:1 hay 20 veces
menos acciones, asi que sin esto el filtro de volumen compara escalas distintas
justo en los dias que mas interesan.

Caso testigo (GCTK, reverse 20:1 el 2025-02-04): el maximo crudo del 29-ene es
0,1115 y en escala post-split son 2,23. Sin ajustar, una condicion
"Close cruza por encima del maximo de los ultimos X dias" se cumple en la
primera vela del dia, siempre, sin error y sin log.

Medido sobre los dias de gap >=20%: un split cae dentro de la ventana en el
4,3% de los casos a 30 dias, el 11,0% a 6 meses y el 16,9% a un ano.

USO
---
    D:/Backtester/backend/.venv/Scripts/python.exe backend/scripts/construir_daily_overhead.py

Lee `LOCAL_LAKE_DIR` y `OVERHEAD_DAILY_PARQUET` de backend/.env.
Se puede volver a lanzar cuando quiera: reescribe el fichero entero.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import duckdb
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parents[1]
load_dotenv(BASE / ".env")

LAGO = os.getenv("LOCAL_LAKE_DIR", "").strip().rstrip("/")
DESTINO = os.getenv(
    "OVERHEAD_DAILY_PARQUET", "D:/lago_backtester/overhead/daily_overhead.parquet"
).strip()
MEMORIA = os.getenv("DUCKDB_MEMORY_LIMIT", "3GB")
SPILL = os.getenv("DUCKDB_SPILL_DIR", "").strip()


def main() -> int:
    if not LAGO:
        print("[ERROR] LOCAL_LAKE_DIR no esta puesto en backend/.env.")
        print("        Este script solo sabe leer el lago local en disco.")
        return 1

    dm = f"{LAGO}/cold_storage/daily_metrics/*/*/*.parquet"
    splits = f"{LAGO}/cold_storage/splits/*.parquet"
    if not Path(f"{LAGO}/cold_storage/daily_metrics").is_dir():
        print(f"[ERROR] No encuentro {LAGO}/cold_storage/daily_metrics")
        return 1

    Path(DESTINO).parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{MEMORIA}'")
    if SPILL:
        Path(SPILL).mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{SPILL}'")

    print(f"  lago    : {LAGO}")
    print(f"  destino : {DESTINO}")
    print("  construyendo (ordenado por ticker: es lo que hace rapida la lectura)...", flush=True)

    t0 = time.time()
    con.execute(f"""
        COPY (
            WITH sf AS (
                -- product() cancela solo los pares reverse+forward del mismo dia
                -- (PMD 5000:1 + 1:5000). NO deduplicar: §6B.3 del lago.
                SELECT ticker, CAST(execution_date AS DATE) AS d,
                       product(CAST(split_from AS DOUBLE) / CAST(split_to AS DOUBLE)) AS f
                FROM read_parquet('{splits}')
                GROUP BY 1, 2
            ),
            base AS (
                SELECT ticker, CAST("timestamp" AS DATE) AS d,
                       CAST(rth_open   AS FLOAT) AS o,
                       CAST(rth_high   AS FLOAT) AS h,
                       CAST(rth_low    AS FLOAT) AS l,
                       CAST(rth_close  AS FLOAT) AS c,
                       CAST(rth_volume AS FLOAT) AS v
                FROM read_parquet('{dm}', hive_partitioning=true)
                WHERE rth_open IS NOT NULL
            ),
            j AS (
                SELECT b.*, COALESCE(sf.f, 1.0) AS f
                FROM base b LEFT JOIN sf USING (ticker, d)
            )
            SELECT ticker, d, o, h, l, c, v,
                   -- Producto en log para no perder precision con los
                   -- contrasplits salvajes (los hay de 100.000:1).
                   exp(sum(ln(f)) OVER (PARTITION BY ticker ORDER BY d
                                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))
                       AS cum_split
            FROM j
            ORDER BY ticker, d
        ) TO '{DESTINO}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)
    """)
    seg = time.time() - t0

    filas, tickers, d0, d1 = con.execute(
        f"SELECT count(*), count(DISTINCT ticker), min(d), max(d) FROM read_parquet('{DESTINO}')"
    ).fetchone()
    mb = Path(DESTINO).stat().st_size / 1e6

    print(f"\n  LISTO en {seg:.0f}s")
    print(f"  {filas:,} filas | {tickers:,} tickers | {d0} -> {d1} | {mb:.0f} MB")

    ajustados = con.execute(
        f"SELECT count(*) FROM read_parquet('{DESTINO}') WHERE cum_split <> 1.0"
    ).fetchone()[0]
    print(f"  filas con algun split por delante: {ajustados:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
