"""
Derivado de Market Analysis (Patch v2.1) — backfill/actualización sobre el data lake GCS.

Genera, POR MES, a partir de intraday_1m + daily_metrics (un solo scan de intraday):

  1. cold_storage/derived/ma_daily/ma_daily_{YYYY-MM}.parquet   (idempotente por mes)
       ticker · date · m0_return_pct · m90_return_pct · max_spike_5m_pct
       - m0/m90: close de la última vela RTH ≤ 09:30 / ≤ 11:00 vs rth_open (misma
         semántica asof que m30/m60_return_pct del processor) → franjas 09:30/11:00
         de Ventanas de Fade.
       - max_spike_5m_pct: max sobre la sesión 04:00–16:00 de
         (high_t − close_{t−5min})/close_{t−5min}×100 con pares estrictos de velas
         a 5 min → filtro black swan (§01.3).

  2. cold_storage/derived/ma_monthly_curves.parquet             (fichero único)
       month · franja · avg_change · avg_gap_pct — curvas de Avg Change from Open
       (MA-04) precalculadas sobre el UNIVERSO ESTÁNDAR: gap_pct ≥ 30, vol día
       (PM+RTH) ≥ 1M, tipos CS/ADRC/OS y filtros de calidad §01 (gap ≤ 1000,
       sin reverse split ≤5d, sin split same-day, sin black swan). Los meses del
       rango procesado REEMPLAZAN a los existentes en el fichero; el resto se conserva.

  3. (--splits / refresh_splits_from_api) parquet ADITIVO en cold_storage/splits/
     con los splits nuevos de la API Massive desde el máximo de la tabla (la vista
     es read_parquet del prefijo → añadir fichero = añadir filas; schema idéntico:
     ticker VARCHAR · execution_date DATE · split_from DOUBLE · split_to DOUBLE).

Diseño §7-B del PRD del patch: TODO es aditivo — no toca daily_metrics ni
intraday_1m ni ficheros existentes (borrar cold_storage/derived/ lo revierte).

Uso:
  python scripts/backfill_ma_derived.py --start 2025-06 --end 2026-07 [--no-curves] [--splits]

Lo invoca también catchup_gcs.py al final de cada run (MA_DERIVED_ENABLED=true)
para el/los meses tocados. Coste medido (07-jul-2026, red doméstica): ~2-4 min/mes;
en prod junto al bucket, menos. El backfill histórico completo se lanza por rangos.
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

import duckdb
import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# Filtros de calidad: misma fuente de verdad que el endpoint (funciones puras).
from app.services.market_analysis_service import (  # noqa: E402
    BLACK_SWAN_SPIKE_MAX_PCT,
    QUALITY_GAP_MAX_PCT,
    REVERSE_SPLIT_LOOKBACK_DAYS,
    build_split_index,
)

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s',
                    datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

GCS_BUCKET = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')
GCS_HMAC_KEY = os.getenv('GCS_HMAC_KEY', '')
GCS_HMAC_SECRET = os.getenv('GCS_HMAC_SECRET', '')
MASSIVE_API_KEY = os.getenv('MASSIVE_API_KEY', '')
MASSIVE_BASE_URL = os.getenv('MASSIVE_API_BASE_URL', 'https://api.massive.com')

DERIVED_DAILY = f"gs://{GCS_BUCKET}/cold_storage/derived/ma_daily"
CURVES_PATH = f"gs://{GCS_BUCKET}/cold_storage/derived/ma_monthly_curves.parquet"
SPLITS_GLOB = f"gs://{GCS_BUCKET}/cold_storage/splits/*.parquet"

# Universo estándar de las curvas MA-04 (§7-C-Q3 del PRD del patch; la UI lo etiqueta)
CURVES_MIN_GAP = 30.0
CURVES_MIN_DAY_VOLUME = 1_000_000.0

_MINS = ("(CAST(extract(hour FROM timestamp) AS INTEGER) * 60 "
         "+ CAST(extract(minute FROM timestamp) AS INTEGER))")


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"""
        SET s3_endpoint='storage.googleapis.com';
        SET s3_access_key_id='{GCS_HMAC_KEY}';
        SET s3_secret_access_key='{GCS_HMAC_SECRET}';
        SET s3_url_style='path';
    """)
    con.execute(f"SET memory_limit='{os.getenv('DUCKDB_MEMORY_LIMIT', '4GB')}'")
    spill = os.getenv('DUCKDB_SPILL_DIR', '/tmp/duckdb_spill')
    os.makedirs(spill, exist_ok=True)
    con.execute(f"SET temp_directory='{spill}'")
    con.execute(f"""
        CREATE VIEW daily_metrics AS SELECT * FROM read_parquet(
            'gs://{GCS_BUCKET}/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true);
    """)
    con.execute(f"""
        CREATE VIEW intraday_1m AS SELECT * FROM read_parquet(
            'gs://{GCS_BUCKET}/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true);
    """)
    con.execute(f"CREATE VIEW splits AS SELECT * FROM read_parquet('{SPLITS_GLOB}')")
    con.execute(f"""
        CREATE VIEW tickers AS SELECT * FROM read_parquet(
            'gs://{GCS_BUCKET}/cold_storage/tickers/*.parquet');
    """)
    return con


# ─── Splits desde la API (tail de la tabla del lake) ─────────────────────────

def refresh_splits_from_api(con: duckdb.DuckDBPyConnection | None = None) -> int:
    """Trae de /v3/reference/splits los splits con execution_date > max(tabla)−7d,
    deduplica contra la tabla y escribe un parquet ADITIVO. Devuelve nº añadidos."""
    if not MASSIVE_API_KEY:
        logger.warning("MASSIVE_API_KEY no configurada; skip refresh de splits")
        return 0
    own = con is None
    if own:
        con = _connect()
    try:
        max_d = con.execute("SELECT MAX(execution_date) FROM splits").fetchone()[0]
        since = ((max_d or date(2012, 1, 1)) - timedelta(days=7)).isoformat()
        logger.info(f"Splits en tabla hasta {max_d}; pidiendo API desde {since}")

        rows, url, params = [], f"{MASSIVE_BASE_URL}/v3/reference/splits", {
            "execution_date.gte": since, "limit": 1000, "order": "asc",
            "sort": "execution_date", "apiKey": MASSIVE_API_KEY,
        }
        for _ in range(40):  # 40k splits de margen — nunca se da
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            for r in data.get("results") or []:
                rows.append({
                    "ticker": r.get("ticker"),
                    "execution_date": r.get("execution_date"),
                    "split_from": r.get("split_from"),
                    "split_to": r.get("split_to"),
                })
            next_url = data.get("next_url")
            if not next_url:
                break
            url, params = next_url, {"apiKey": MASSIVE_API_KEY}

        if not rows:
            logger.info("API sin splits nuevos")
            return 0
        df = pd.DataFrame(rows).dropna(subset=["ticker", "execution_date"])
        df["execution_date"] = pd.to_datetime(df["execution_date"]).dt.date
        con.register("api_splits", df)
        # Anti-join contra lo existente y CAST al schema EXACTO de la vista union
        # (VARCHAR, DATE, DOUBLE, DOUBLE): un fichero con tipos distintos rompería
        # read_parquet del prefijo para TODOS los consumidores.
        new = con.execute("""
            SELECT CAST(a.ticker AS VARCHAR) AS ticker,
                   CAST(a.execution_date AS DATE) AS execution_date,
                   CAST(a.split_from AS DOUBLE) AS split_from,
                   CAST(a.split_to AS DOUBLE) AS split_to
            FROM api_splits a
            ANTI JOIN splits s
              ON s.ticker = a.ticker AND s.execution_date = a.execution_date
        """).fetchdf()
        if new.empty:
            logger.info("API sin splits que no estuvieran ya en la tabla")
            return 0
        con.register("new_splits", new)
        out = (f"gs://{GCS_BUCKET}/cold_storage/splits/"
               f"api_splits_{date.today().strftime('%Y%m%d')}.parquet")
        con.execute(f"COPY (SELECT * FROM new_splits ORDER BY execution_date, ticker) "
                    f"TO '{out}' (FORMAT PARQUET)")
        logger.info(f"Splits añadidos: {len(new)} → {out} "
                    f"(reverse: {int((new['split_to'] < new['split_from']).sum())})")
        return len(new)
    finally:
        if own:
            con.close()


# ─── Derivado mensual (scalars + curvas) en UN scan de intraday ──────────────

def _load_month_bars(con, year: int, month: int) -> int:
    """Materializa las velas del mes (sesión 04:00–16:00) en una TEMP TABLE para
    que scalars y curvas compartan un único scan del parquet remoto."""
    con.execute("DROP TABLE IF EXISTS bars")
    con.execute(f"""
        CREATE TEMP TABLE bars AS
        SELECT ticker, date, {_MINS} AS mins, high, close
        FROM intraday_1m
        WHERE year = {year} AND month = {month}
          AND {_MINS} BETWEEN 240 AND 959
    """)
    return con.execute("SELECT COUNT(*) FROM bars").fetchone()[0]


def _month_scalars(con, year: int, month: int) -> pd.DataFrame:
    """ticker/date/m0/m90/max_spike del mes, LEFT-join sobre daily_metrics (una
    fila por fila de daily_metrics: los huecos quedan NULL, el servicio hace fail-open)."""
    return con.execute(f"""
        WITH m0 AS (
            SELECT ticker, date, ARG_MAX(close, mins) AS close
            FROM bars WHERE mins = 570 GROUP BY 1, 2
        ),
        m90 AS (
            SELECT ticker, date, ARG_MAX(close, mins) AS close
            FROM bars WHERE mins BETWEEN 570 AND 660 GROUP BY 1, 2
        ),
        spike AS (
            SELECT b.ticker, b.date,
                   MAX((b.high - p.close) / p.close * 100) AS max_spike_5m_pct
            FROM bars b
            JOIN bars p ON p.ticker = b.ticker AND p.date = b.date AND p.mins = b.mins - 5
            WHERE p.close > 0
            GROUP BY 1, 2
        )
        SELECT d.ticker,
               CAST(d.timestamp AS DATE) AS date,
               CASE WHEN d.rth_open > 0 AND m0.close > 0
                    THEN (m0.close - d.rth_open) / d.rth_open * 100 END AS m0_return_pct,
               CASE WHEN d.rth_open > 0 AND m90.close > 0
                    THEN (m90.close - d.rth_open) / d.rth_open * 100 END AS m90_return_pct,
               spike.max_spike_5m_pct
        FROM daily_metrics d
        LEFT JOIN m0    ON m0.ticker = d.ticker    AND m0.date = CAST(d.timestamp AS DATE)
        LEFT JOIN m90   ON m90.ticker = d.ticker   AND m90.date = CAST(d.timestamp AS DATE)
        LEFT JOIN spike ON spike.ticker = d.ticker AND spike.date = CAST(d.timestamp AS DATE)
        WHERE d.year = {year} AND d.month = {month}
    """).fetchdf()


def _month_curve(con, year: int, month: int, scalars: pd.DataFrame,
                 splits_records: list[dict]) -> list[dict]:
    """Puntos de la curva MA-04 del mes sobre el universo estándar + filtros §01."""
    uni = con.execute(f"""
        SELECT d.ticker, CAST(d.timestamp AS DATE) AS date, d.rth_open, d.gap_pct
        FROM daily_metrics d
        JOIN tickers t ON d.ticker = t.ticker
        WHERE d.year = {year} AND d.month = {month}
          AND d.gap_pct >= {CURVES_MIN_GAP} AND d.gap_pct <= {QUALITY_GAP_MAX_PCT}
          AND (d.pm_volume + d.rth_volume) >= {CURVES_MIN_DAY_VOLUME}
          AND d.rth_open > 0
          AND t.type IN ('CS', 'ADRC', 'OS')
    """).fetchdf()
    if uni.empty:
        return []
    # fetchdf devuelve DATE como Timestamp — normalizar a datetime.date para
    # comparar con build_split_index y para claves string estables.
    uni["date"] = pd.to_datetime(uni["date"]).dt.date

    # Reverse split ≤5d / same-day (misma semántica que apply_quality_filters)
    reverse_idx, anyday_idx = build_split_index(splits_records)
    lookback = timedelta(days=REVERSE_SPLIT_LOOKBACK_DAYS)

    def _clean(row) -> bool:
        tk, d = str(row["ticker"]).upper(), row["date"]
        if d in anyday_idx.get(tk, ()):
            return False
        if any(d - lookback < ed <= d for ed in reverse_idx.get(tk, ())):
            return False
        return True

    uni = uni[uni.apply(_clean, axis=1)]

    # Black swan con los scalars recién calculados (mismo scan del mes)
    swans = scalars[scalars["max_spike_5m_pct"] > BLACK_SWAN_SPIKE_MAX_PCT]
    if not swans.empty:
        swan_keys = set(zip(swans["ticker"].astype(str),
                            swans["date"].astype(str).str[:10]))
        uni = uni[~uni.apply(
            lambda r: (str(r["ticker"]), str(r["date"])[:10]) in swan_keys, axis=1)]
    if uni.empty:
        return []

    con.register("uni", uni)
    pts = con.execute("""
        SELECT printf('%02d:%02d', ((b.mins // 30) * 30) // 60, ((b.mins // 30) * 30) % 60) AS franja,
               AVG((b.close - u.rth_open) / u.rth_open * 100) AS avg_change
        FROM bars b
        JOIN uni u ON b.ticker = u.ticker AND b.date = u.date
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    con.unregister("uni")

    month_str = f"{year:04d}-{month:02d}"
    avg_gap = float(uni["gap_pct"].mean())
    return [{"month": month_str, "franja": f, "avg_change": float(c or 0.0),
             "avg_gap_pct": avg_gap} for f, c in pts]


def _write_ma_daily(con, scalars: pd.DataFrame, year: int, month: int) -> None:
    con.register("scalars", scalars)
    out = f"{DERIVED_DAILY}/ma_daily_{year:04d}-{month:02d}.parquet"
    con.execute(f"""
        COPY (
            SELECT CAST(ticker AS VARCHAR) AS ticker, CAST(date AS DATE) AS date,
                   CAST(m0_return_pct AS DOUBLE) AS m0_return_pct,
                   CAST(m90_return_pct AS DOUBLE) AS m90_return_pct,
                   CAST(max_spike_5m_pct AS DOUBLE) AS max_spike_5m_pct
            FROM scalars ORDER BY date, ticker
        ) TO '{out}' (FORMAT PARQUET)
    """)
    con.unregister("scalars")
    logger.info(f"  ma_daily → {out} ({len(scalars)} filas)")


def _rewrite_curves(con, new_rows: list[dict], months_processed: set[str]) -> None:
    """Reemplaza en el fichero único de curvas los meses procesados; conserva el resto."""
    keep = pd.DataFrame(columns=["month", "franja", "avg_change", "avg_gap_pct"])
    try:
        existing = con.execute(
            f"SELECT month, franja, avg_change, avg_gap_pct FROM read_parquet('{CURVES_PATH}')"
        ).fetchdf()
        keep = existing[~existing["month"].isin(months_processed)]
    except Exception:
        pass  # primera generación: no existe aún
    new_df = pd.DataFrame(new_rows)
    frames = [df for df in (keep, new_df) if not df.empty]
    if not frames:
        logger.warning("Curvas: nada que escribir")
        return
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values(["month", "franja"])
    con.register("curves", merged)
    con.execute(f"""
        COPY (
            SELECT CAST(month AS VARCHAR) AS month, CAST(franja AS VARCHAR) AS franja,
                   CAST(avg_change AS DOUBLE) AS avg_change,
                   CAST(avg_gap_pct AS DOUBLE) AS avg_gap_pct
            FROM curves ORDER BY month, franja
        ) TO '{CURVES_PATH}' (FORMAT PARQUET)
    """)
    con.unregister("curves")
    logger.info(f"Curvas MA-04 → {CURVES_PATH} ({merged['month'].nunique()} meses)")


def _month_range(start_ym: tuple[int, int], end_ym: tuple[int, int]):
    y, m = start_ym
    while (y, m) <= end_ym:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def run_backfill(start_ym: tuple[int, int], end_ym: tuple[int, int],
                 with_curves: bool = True) -> None:
    import time
    con = _connect()
    try:
        splits_records = con.execute(
            "SELECT ticker, execution_date, split_from, split_to FROM splits"
        ).fetchdf().to_dict("records") if with_curves else []

        curve_rows: list[dict] = []
        months_processed: set[str] = set()
        for year, month in _month_range(start_ym, end_ym):
            t0 = time.time()
            n_bars = _load_month_bars(con, year, month)
            if n_bars == 0:
                logger.info(f"{year}-{month:02d}: sin velas intraday, skip")
                continue
            scalars = _month_scalars(con, year, month)
            _write_ma_daily(con, scalars, year, month)
            if with_curves:
                curve_rows.extend(_month_curve(con, year, month, scalars, splits_records))
                months_processed.add(f"{year:04d}-{month:02d}")
            logger.info(f"{year}-{month:02d}: {n_bars:,} velas · {len(scalars)} ticker-días "
                        f"· {time.time() - t0:.1f}s")
        if with_curves and months_processed:
            _rewrite_curves(con, curve_rows, months_processed)
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, help="YYYY-MM (inclusive)")
    ap.add_argument("--end", required=True, help="YYYY-MM (inclusive)")
    ap.add_argument("--no-curves", action="store_true", help="solo ma_daily, sin curvas MA-04")
    ap.add_argument("--splits", action="store_true", help="refrescar splits desde la API antes")
    args = ap.parse_args()

    sy, sm = int(args.start[:4]), int(args.start[5:7])
    ey, em = int(args.end[:4]), int(args.end[5:7])
    if args.splits:
        refresh_splits_from_api()
    run_backfill((sy, sm), (ey, em), with_curves=not args.no_curves)
    logger.info("=== Done ===")


if __name__ == "__main__":
    main()
