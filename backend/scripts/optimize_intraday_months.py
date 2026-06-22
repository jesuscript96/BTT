import os
import sys
import duckdb
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

GCS_BUCKET = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')
GCS_HMAC_KEY = os.getenv('GCS_HMAC_KEY', '')
GCS_HMAC_SECRET = os.getenv('GCS_HMAC_SECRET', '')

# Meses a optimizar — añadir/quitar según auditoría
MONTHS_TO_OPTIMIZE = [
    (2024, 7),
    (2025, 1),
    (2025, 2),
    # Backfill marzo-junio 2026 (intraday revivido vía catchup_gcs.py)
    (2026, 3),
    (2026, 4),
    (2026, 5),
    (2026, 6),
]


def get_connection():
    con = duckdb.connect()
    con.execute(f"""
        INSTALL httpfs; LOAD httpfs;
        SET s3_endpoint='storage.googleapis.com';
        SET s3_access_key_id='{GCS_HMAC_KEY}';
        SET s3_secret_access_key='{GCS_HMAC_SECRET}';
        SET s3_url_style='path';
        SET memory_limit='8GB';
        SET threads=4;
    """)
    return con


def optimize_month(year: int, month: int, dry_run: bool = False):
    """
    Lee el parquet RAW de un mes, ordena por ticker,
    escribe como OPT en intraday_1m_optimized.
    """
    raw_path = f"gs://{GCS_BUCKET}/cold_storage/intraday_1m/year={year}/month={month}/*.parquet"
    opt_path = f"gs://{GCS_BUCKET}/cold_storage/intraday_1m_optimized/year={year}/month={month}/data.parquet"

    logger.info(f"[{year}-{month:02d}] Starting optimization...")
    logger.info(f"  RAW: {raw_path}")
    logger.info(f"  OPT: {opt_path}")

    if dry_run:
        logger.info(f"  [DRY RUN] Would write to {opt_path}")
        return

    con = get_connection()

    try:
        # Verificar que existe el RAW
        count = con.execute(f"""
            SELECT COUNT(*) FROM read_parquet(
                '{raw_path}',
                hive_partitioning=true
            )
        """).fetchone()[0]

        if count == 0:
            logger.warning(f"  [{year}-{month:02d}] No data in RAW, skipping")
            return

        logger.info(f"  [{year}-{month:02d}] {count:,} rows to optimize...")

        # Ordenar por ticker y escribir OPT
        con.execute(f"""
            COPY (
                SELECT *
                FROM read_parquet(
                    '{raw_path}',
                    hive_partitioning=true
                )
                ORDER BY ticker
            )
            TO '{opt_path}'
            (FORMAT PARQUET)
        """)

        # Verificar resultado
        opt_count = con.execute(f"""
            SELECT COUNT(*) FROM read_parquet('{opt_path}')
        """).fetchone()[0]

        logger.info(f"  [{year}-{month:02d}] ✅ Done: {opt_count:,} rows written to OPT")

    except Exception as e:
        logger.error(f"  [{year}-{month:02d}] ❌ Failed: {e}")
        raise
    finally:
        con.close()


def main():
    dry_run = '--dry-run' in sys.argv

    if dry_run:
        logger.info("=== DRY RUN MODE — no writes to GCS ===")

    logger.info(f"=== Optimizing {len(MONTHS_TO_OPTIMIZE)} months ===")

    for year, month in MONTHS_TO_OPTIMIZE:
        try:
            optimize_month(year, month, dry_run=dry_run)
        except Exception as e:
            logger.error(f"Skipping {year}-{month:02d} due to error: {e}")
            continue

    logger.info("=== Done ===")


if __name__ == "__main__":
    main()
