#!/usr/bin/env python3
"""
generate_adjusted_lake.py — Materializa parquet ajustado por splits (back-adjust).

Para cada barra del lake raw:
  price_adj  = price_raw  × factor
  volume_adj = volume_raw ÷ factor

El factor es el producto acumulativo de (split_from/split_to) para TODOS los
splits con execution_date > fecha_barra. Sin splits posteriores → factor 1.0.

Output: mismo schema y tipos que el original, valores ajustados. Path paralelo
con sufijo _adj para no tocar el raw.

Uso (dentro del contenedor, que tiene GCS creds + /lake mount):
  python scripts/generate_adjusted_lake.py --start 2026-01 --end 2026-08 [--validate]

Fuentes:
  intraday_1m     → disco local  (/lake/cold_storage/intraday_1m/...)
  daily_metrics   → GCS          (gs://.../cold_storage/daily_metrics/...)
  splits          → GCS          (gs://.../cold_storage/splits/*.parquet)
"""

import argparse
import logging
import os
import sys
import time

import duckdb

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

GCS_BUCKET = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
LAKE_DIR = os.getenv("LOCAL_LAKE_DIR", "/lake")
GCS_HMAC_KEY = os.getenv("GCS_HMAC_KEY", "")
GCS_HMAC_SECRET = os.getenv("GCS_HMAC_SECRET", "")

SPLITS_GCS = f"gs://{GCS_BUCKET}/cold_storage/splits/*.parquet"
DAILY_GCS = f"gs://{GCS_BUCKET}/cold_storage/daily_metrics"
INTRADAY_LOCAL = f"{LAKE_DIR}/cold_storage/intraday_1m"

INTRADAY_OUT = f"{LAKE_DIR}/cold_storage/intraday_1m_adj"
DAILY_OUT = f"{LAKE_DIR}/cold_storage/daily_metrics_adj"


def connect() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.execute("INSTALL httpfs; LOAD httpfs;")
    c.execute("SET s3_endpoint='storage.googleapis.com';")
    c.execute(f"SET s3_access_key_id='{GCS_HMAC_KEY}';")
    c.execute(f"SET s3_secret_access_key='{GCS_HMAC_SECRET}';")
    c.execute("SET s3_url_style='path';")
    c.execute(f"SET memory_limit='{os.getenv('DUCKDB_MEMORY_LIMIT', '8GB')}';")
    c.execute("SET temp_directory='/tmp/duckdb_spill';")
    c.execute("SET enable_progress_bar = false;")
    return c


def _month_iter(start_ym: str, end_ym: str):
    y, m = int(start_ym[:4]), int(start_ym[5:7])
    ey, em = int(end_ym[:4]), int(end_ym[5:7])
    while (y, m) <= (ey, em):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _compute_bar_factors(con, raw_glob, year, month):
    """Crea temp table bar_factors con (ticker, bar_date, adj_factor).

    El factor = Π(split_from/split_to) para splits con execution_date > bar_date.
    Si no hay splits posteriores → 1.0.
    """
    con.execute("DROP TABLE IF EXISTS bar_factors")
    con.execute(f"""
        CREATE TEMP TABLE bar_factors AS
        WITH distinct_dates AS (
            SELECT DISTINCT ticker, CAST(timestamp AS DATE) AS bar_date
            FROM read_parquet('{raw_glob}', hive_partitioning=true)
            WHERE year = {year} AND month = {month}
        ),
        with_splits AS (
            SELECT
                d.ticker,
                d.bar_date,
                COALESCE(
                    EXP(SUM(
                        LN(CAST(s.split_from AS DOUBLE) / CAST(s.split_to AS DOUBLE))
                    )),
                    1.0
                ) AS adj_factor
            FROM distinct_dates d
            LEFT JOIN read_parquet('{SPLITS_GCS}') s
                ON d.ticker = s.ticker
                AND CAST(s.execution_date AS DATE) > d.bar_date
            GROUP BY d.ticker, d.bar_date
        )
        SELECT * FROM with_splits
    """)
    total = con.execute("SELECT COUNT(*) FROM bar_factors").fetchone()[0]
    adjusted = con.execute(
        "SELECT COUNT(*) FROM bar_factors WHERE adj_factor < 0.999 OR adj_factor > 1.001"
    ).fetchone()[0]
    log.info(f"  Factors: {adjusted}/{total} (ticker,date) con factor != 1.0")
    return total, adjusted


# ─── intraday_1m ─────────────────────────────────────────────────────────────

def adjust_intraday_month(con, year, month):
    raw = f"{INTRADAY_LOCAL}/year={year}/month={month}/*.parquet"
    out_dir = f"{INTRADAY_OUT}/year={year}/month={month}"
    out = f"{out_dir}/adjusted.parquet"
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    log.info(f"intraday_1m {year}-{month:02d}: calculando factores...")
    _compute_bar_factors(con, f"{INTRADAY_LOCAL}/year={year}/month={month}/*.parquet", year, month)

    raw_count = con.execute(f"""
        SELECT COUNT(*) FROM read_parquet('{raw}', hive_partitioning=true)
        WHERE year = {year} AND month = {month}
    """).fetchone()[0]

    log.info(f"intraday_1m {year}-{month:02d}: escribiendo {raw_count:,} filas ajustadas...")
    con.execute(f"""
        COPY (
            SELECT
                i.ticker,
                i.open   * COALESCE(f.adj_factor, 1.0) AS open,
                i.high   * COALESCE(f.adj_factor, 1.0) AS high,
                i.low    * COALESCE(f.adj_factor, 1.0) AS low,
                i.close  * COALESCE(f.adj_factor, 1.0) AS close,
                CAST(i.volume / COALESCE(f.adj_factor, 1.0) AS BIGINT) AS volume,
                CAST(i.transactions / COALESCE(f.adj_factor, 1.0) AS BIGINT) AS transactions,
                i.timestamp,
                i.date,
                i.month,
                i.year
            FROM read_parquet('{raw}', hive_partitioning=true) i
            LEFT JOIN bar_factors f
                ON i.ticker = f.ticker
                AND CAST(i.timestamp AS DATE) = f.bar_date
            WHERE i.year = {year} AND i.month = {month}
        ) TO '{out}' (FORMAT PARQUET)
    """)
    dt = time.time() - t0
    log.info(f"intraday_1m {year}-{month:02d}: done ({dt:.1f}s) → {out}")


# ─── daily_metrics ───────────────────────────────────────────────────────────

def adjust_daily_month(con, year, month):
    raw = f"{DAILY_GCS}/year={year}/month={month}/*.parquet"
    out_dir = f"{DAILY_OUT}/year={year}/month={month}"
    out = f"{out_dir}/adjusted.parquet"
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    log.info(f"daily_metrics {year}-{month:02d}: calculando factores...")
    _compute_bar_factors(con, raw, year, month)

    raw_count = con.execute(f"""
        SELECT COUNT(*) FROM read_parquet('{raw}', hive_partitioning=true)
        WHERE year = {year} AND month = {month}
    """).fetchone()[0]

    log.info(f"daily_metrics {year}-{month:02d}: escribiendo {raw_count:,} filas ajustadas...")
    con.execute(f"""
        COPY (
            SELECT
                d.ticker,
                d.timestamp,
                d.open     * COALESCE(f.adj_factor, 1.0) AS open,
                d.high     * COALESCE(f.adj_factor, 1.0) AS high,
                d.low      * COALESCE(f.adj_factor, 1.0) AS low,
                d.close    * COALESCE(f.adj_factor, 1.0) AS close,
                CAST(d.volume       / COALESCE(f.adj_factor, 1.0) AS BIGINT) AS volume,
                CAST(d.transactions / COALESCE(f.adj_factor, 1.0) AS BIGINT) AS transactions,
                CAST(d.pm_volume    / COALESCE(f.adj_factor, 1.0) AS BIGINT) AS pm_volume,
                d.pm_high  * COALESCE(f.adj_factor, 1.0) AS pm_high,
                d.pm_low   * COALESCE(f.adj_factor, 1.0) AS pm_low,
                d.pm_high_time,
                d.pm_low_time,
                d.gap_pct,
                d.pmh_gap_pct,
                d.pmh_fade_pct,
                CAST(d.rth_volume / COALESCE(f.adj_factor, 1.0) AS BIGINT) AS rth_volume,
                d.rth_open * COALESCE(f.adj_factor, 1.0) AS rth_open,
                d.rth_high * COALESCE(f.adj_factor, 1.0) AS rth_high,
                d.rth_low  * COALESCE(f.adj_factor, 1.0) AS rth_low,
                d.rth_close* COALESCE(f.adj_factor, 1.0) AS rth_close,
                d.rth_run_pct,
                d.rth_fade_pct,
                d.rth_range_pct,
                d.hod_time,
                d.lod_time,
                d.m15_return_pct,
                d.m30_return_pct,
                d.m60_return_pct,
                d.m180_return_pct,
                d.close_1559 * COALESCE(f.adj_factor, 1.0) AS close_1559,
                d.last_close * COALESCE(f.adj_factor, 1.0) AS last_close,
                d.day_return_pct,
                d.prev_close * COALESCE(f.adj_factor, 1.0) AS prev_close,
                CAST(d.eod_volume / COALESCE(f.adj_factor, 1.0) AS BIGINT) AS eod_volume,
                d.year,
                d.month
            FROM read_parquet('{raw}', hive_partitioning=true) d
            LEFT JOIN bar_factors f
                ON d.ticker = f.ticker
                AND CAST(d.timestamp AS DATE) = f.bar_date
            WHERE d.year = {year} AND d.month = {month}
        ) TO '{out}' (FORMAT PARQUET)
    """)
    dt = time.time() - t0
    log.info(f"daily_metrics {year}-{month:02d}: done ({dt:.1f}s) → {out}")


# ─── validación ──────────────────────────────────────────────────────────────

def validate_month(con, year, month):
    """Checks: row count match, gap_pct invariante, value conservation."""
    raw_i = f"{INTRADAY_LOCAL}/year={year}/month={month}/*.parquet"
    adj_i = f"{INTRADAY_OUT}/year={year}/month={month}/*.parquet"
    raw_d = f"{DAILY_GCS}/year={year}/month={month}/*.parquet"
    adj_d = f"{DAILY_OUT}/year={year}/month={month}/*.parquet"

    log.info(f"VALIDACIÓN {year}-{month:02d}:")

    for name, rp, ap in [("intraday_1m", raw_i, adj_i), ("daily_metrics", raw_d, adj_d)]:
        rc = con.execute(f"SELECT COUNT(*) FROM read_parquet('{rp}', hive_partitioning=true) WHERE year={year} AND month={month}").fetchone()[0]
        ac = con.execute(f"SELECT COUNT(*) FROM read_parquet('{ap}', hive_partitioning=true) WHERE year={year} AND month={month}").fetchone()[0]
        status = "OK" if rc == ac else "FAIL"
        log.info(f"  {name}: filas raw={rc:,} adj={ac:,} → {status}")

    # Invariancia gap_pct (factor cancela en ratio)
    log.info(f"  gap_pct invariante en daily_metrics (spot-check)...")
    diff = con.execute(f"""
        WITH r AS (SELECT ticker, timestamp, gap_pct FROM read_parquet('{raw_d}', hive_partitioning=true) WHERE year={year} AND month={month}),
             a AS (SELECT ticker, timestamp, gap_pct FROM read_parquet('{adj_d}', hive_partitioning=true) WHERE year={year} AND month={month})
        SELECT COUNT(*) FROM r JOIN a USING(ticker, timestamp)
        WHERE ABS(r.gap_pct - a.gap_pct) > 0.001
    """).fetchone()[0]
    log.info(f"    filas con gap_pct distinto >0.001: {diff} (esperado: 0) → {'OK' if diff == 0 else 'FAIL'}")

    # Conservación valor: open×volume
    log.info(f"  conservación open×volume en intraday (spot-check)...")
    valdiff = con.execute(f"""
        WITH r AS (SELECT ticker, timestamp, open, volume FROM read_parquet('{raw_i}', hive_partitioning=true) WHERE year={year} AND month={month}),
             a AS (SELECT ticker, timestamp, open, volume FROM read_parquet('{adj_i}', hive_partitioning=true) WHERE year={year} AND month={month})
        SELECT COUNT(*) FROM r JOIN a USING(ticker, timestamp)
        WHERE ABS(r.open * r.volume - a.open * a.volume) > 1.0
          AND r.volume > 0
    """).fetchone()[0]
    log.info(f"    filas con open×volume distinto: {valdiff} → {'OK' if valdiff == 0 else 'CHECK'}")


# ─── main ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, help="YYYY-MM")
    ap.add_argument("--end", required=True, help="YYYY-MM")
    ap.add_argument("--daily-only", action="store_true", help="solo daily_metrics")
    ap.add_argument("--intraday-only", action="store_true", help="solo intraday_1m")
    ap.add_argument("--validate", action="store_true", help="validar tras generar")
    args = ap.parse_args()

    months = list(_month_iter(args.start, args.end))
    log.info(f"=== Generate adjusted lake: {args.start} → {args.end} ({len(months)} meses) ===")

    con = connect()
    try:
        for year, month in months:
            if not args.daily_only:
                adjust_intraday_month(con, year, month)
            if not args.intraday_only:
                adjust_daily_month(con, year, month)
            if args.validate:
                validate_month(con, year, month)
    finally:
        con.close()
    log.info("=== Done ===")


if __name__ == "__main__":
    main()
