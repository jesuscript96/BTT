"""
Tabla de referencia ticker → sector (PRD docs/market-analysis/PRD_GAPS_BY_SECTOR.md · S1).

Enriquece el universo de gappers (gap_pct >= MIN_GAP) con su SIC/sector (Massive → SEC EDGAR)
y escribe cold_storage/reference/ticker_sector.parquet:
    ticker · sic_code · sic_description · sector · source · updated_at

ADITIVO: no toca daily_metrics/intraday_1m. En request-time se lee esta tabla (nunca la API).
Orden por RECENCIA: los tickers con gap más reciente se enriquecen primero, así las ventanas
5D/30D/90D de la página quedan cubiertas en el primer minuto aunque el histórico siga detrás.

Uso:
    python scripts/build_ticker_sector.py                 # universo gap>=20 completo
    python scripts/build_ticker_sector.py --days 120      # solo tickers con gap en los últimos N días
    python scripts/build_ticker_sector.py --min-gap 20 --workers 12
"""
import argparse
import concurrent.futures as cf
import logging
import os
import sys
from datetime import date, datetime, timezone

import duckdb
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from app.services.sector_service import resolve_sector  # noqa: E402

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

GCS_BUCKET = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')
GCS_HMAC_KEY = os.getenv('GCS_HMAC_KEY', '')
GCS_HMAC_SECRET = os.getenv('GCS_HMAC_SECRET', '')
OUT_PATH = f"gs://{GCS_BUCKET}/cold_storage/reference/ticker_sector.parquet"
MIN_GAP = 20.0


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"""
        SET s3_endpoint='storage.googleapis.com';
        SET s3_access_key_id='{GCS_HMAC_KEY}';
        SET s3_secret_access_key='{GCS_HMAC_SECRET}';
        SET s3_url_style='path';
    """)
    con.execute(f"""CREATE VIEW daily_metrics AS SELECT * FROM read_parquet(
        'gs://{GCS_BUCKET}/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)""")
    con.execute(f"""CREATE VIEW tickers AS SELECT * FROM read_parquet(
        'gs://{GCS_BUCKET}/cold_storage/tickers/*.parquet')""")
    return con


def _universe(con, min_gap: float, days: int | None) -> list[str]:
    """Tickers (CS/ADRC/OS) con gap>=min_gap, ORDENADOS por fecha de gap más reciente desc."""
    where_days = ""
    if days:
        where_days = f"AND d.timestamp >= (SELECT MAX(timestamp) FROM daily_metrics) - INTERVAL '{days} days'"
    rows = con.execute(f"""
        SELECT d.ticker, MAX(d.timestamp) AS last_gap
        FROM daily_metrics d
        JOIN tickers t ON d.ticker = t.ticker AND t.type IN ('CS','ADRC','OS')
        WHERE d.gap_pct >= {min_gap} {where_days}
        GROUP BY d.ticker
        ORDER BY last_gap DESC
    """).fetchall()
    return [r[0] for r in rows]


def _existing(con) -> pd.DataFrame:
    try:
        return con.execute(f"SELECT * FROM read_parquet('{OUT_PATH}')").fetchdf()
    except Exception:
        return pd.DataFrame(columns=["ticker", "sic_code", "sic_description", "sector", "source", "updated_at"])


def build(min_gap: float, days: int | None, workers: int, refresh_all: bool, now_iso: str) -> None:
    con = _connect()
    try:
        universe = _universe(con, min_gap, days)
        logger.info(f"Universo gap>={min_gap}{f' ({days}d)' if days else ''}: {len(universe)} tickers (recientes primero)")

        prev = _existing(con)
        known = set() if refresh_all else set(prev["ticker"].astype(str))
        todo = [t for t in universe if t not in known]
        logger.info(f"Ya en tabla: {len(known)} · a enriquecer: {len(todo)}")
        if not todo:
            logger.info("Nada que hacer.")
            return

        results, done, hit = [], 0, 0
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(resolve_sector, todo):
                r["updated_at"] = now_iso
                results.append(r)
                done += 1
                if r["source"] != "none":
                    hit += 1
                if done % 200 == 0:
                    logger.info(f"  {done}/{len(todo)} · cobertura {hit/done*100:.0f}%")

        new = pd.DataFrame(results)
        merged = pd.concat([prev[~prev["ticker"].isin(new["ticker"])], new], ignore_index=True) \
            if not prev.empty else new
        cov = (merged["source"] != "none").mean() * 100 if len(merged) else 0
        logger.info(f"Total tabla: {len(merged)} · cobertura global {cov:.0f}% · nuevos con dato {hit}/{len(todo)}")

        con.register("out", merged)
        con.execute(f"""COPY (
            SELECT CAST(ticker AS VARCHAR) ticker, CAST(sic_code AS VARCHAR) sic_code,
                   CAST(sic_description AS VARCHAR) sic_description, CAST(sector AS VARCHAR) sector,
                   CAST(source AS VARCHAR) source, CAST(updated_at AS VARCHAR) updated_at
            FROM out ORDER BY ticker
        ) TO '{OUT_PATH}' (FORMAT PARQUET)""")
        logger.info(f"Escrito → {OUT_PATH}")

        # Distribución para sanity
        dist = merged[merged["source"] != "none"]["sector"].value_counts()
        logger.info("Distribución por sector:\n" + dist.to_string())
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-gap", type=float, default=MIN_GAP)
    ap.add_argument("--days", type=int, default=None, help="solo tickers con gap en los últimos N días")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--refresh-all", action="store_true", help="reenriquecer también los ya presentes")
    args = ap.parse_args()
    # timestamp fijo pasado al build (Date.now no disponible dentro de workflows, aquí sí en CLI)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    build(args.min_gap, args.days, args.workers, args.refresh_all, now_iso)
    logger.info("=== Done ===")


if __name__ == "__main__":
    main()
