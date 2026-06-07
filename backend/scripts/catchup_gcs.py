import os
import sys
import time
import json
import logging
import requests
import numpy as np
import pandas as pd
import duckdb
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv('MASSIVE_API_KEY', '')
BASE_URL = os.getenv('MASSIVE_API_BASE_URL', 'https://api.massive.com')
GCS_BUCKET = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')
GCS_HMAC_KEY = os.getenv('GCS_HMAC_KEY', '')
GCS_HMAC_SECRET = os.getenv('GCS_HMAC_SECRET', '')

GAP_PCT_MIN = 5.0        # candidatos con gap >= 5%
PM_RUNNER_MIN = 10.0     # candidatos con pmh estimado >= 10%
MAX_WORKERS = 10
SLEEP_BETWEEN_DAYS = 0.5  # segundos entre días

# ─── Massive client ───────────────────────────────────

def get_grouped_daily(date_str: str) -> list[dict]:
    """OHLCV diario para todo el mercado en una fecha."""
    url = f"{BASE_URL}/v2/aggs/grouped/locale/us/market/stocks/{date_str}"
    r = requests.get(url, params={"apiKey": API_KEY, "adjusted": "true"},
                     verify=False, timeout=15)
    if r.status_code == 200:
        return r.json().get("results", [])
    logger.warning(f"grouped_daily {date_str}: HTTP {r.status_code}")
    return []

def get_1m_bars(ticker: str, date_str: str) -> pd.DataFrame:
    """Barras de 1 minuto para un ticker en una fecha."""
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}"
    r = requests.get(url, params={"apiKey": API_KEY, "adjusted": "true",
                                   "sort": "asc", "limit": 50000},
                     verify=False, timeout=15)
    if r.status_code != 200:
        return pd.DataFrame()
    results = r.json().get("results", [])
    if not results:
        return pd.DataFrame()
    df = pd.DataFrame(results)
    df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                              "l": "low", "c": "close", "v": "volume",
                              "vw": "vwap", "n": "transactions"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df["ticker"] = ticker
    return df[["timestamp", "ticker", "open", "high", "low", "close",
               "volume", "transactions"]]

# ─── Processor ────────────────────────────────────────

def process_day_metrics(ticker: str, df_1m: pd.DataFrame,
                         prev_close: float, date_str: str) -> Optional[dict]:
    """
    Calcula métricas diarias desde barras 1m.
    Replica la lógica de processor_service.py.
    """
    if df_1m.empty:
        return None

    ts = pd.to_datetime(df_1m["timestamp"])

    # Sesiones
    pm_mask = (ts.dt.hour < 9) | ((ts.dt.hour == 9) & (ts.dt.minute < 30))
    rth_mask = (ts.dt.hour > 9) | ((ts.dt.hour == 9) & (ts.dt.minute >= 30))
    rth_mask = rth_mask & (ts.dt.hour < 16)

    pm_df = df_1m[pm_mask]
    rth_df = df_1m[rth_mask]

    if rth_df.empty:
        return None

    # RTH metrics
    rth_open = float(rth_df["open"].iloc[0])
    rth_high = float(rth_df["high"].max())
    rth_low = float(rth_df["low"].min())
    rth_close = float(rth_df["close"].iloc[-1])
    rth_volume = int(rth_df["volume"].sum())

    # PM metrics
    pm_high = float(pm_df["high"].max()) if not pm_df.empty else rth_open
    pm_low = float(pm_df["low"].min()) if not pm_df.empty else rth_open
    pm_volume = int(pm_df["volume"].sum()) if not pm_df.empty else 0
    pm_high_time = ""
    pm_low_time = ""
    if not pm_df.empty:
        pm_high_idx = pm_df["high"].idxmax()
        pm_low_idx = pm_df["low"].idxmin()
        pm_high_time = str(df_1m.loc[pm_high_idx, "timestamp"])[:16]
        pm_low_time = str(df_1m.loc[pm_low_idx, "timestamp"])[:16]

    # Gap metrics
    gap_pct = ((rth_open - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
    pmh_gap_pct = ((pm_high - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
    pmh_fade_pct = ((pm_high - rth_open) / pm_high * 100) if pm_high > 0 else 0.0

    # RTH metrics
    rth_run_pct = ((rth_high - rth_open) / rth_open * 100) if rth_open > 0 else 0.0
    rth_fade_pct = ((rth_high - rth_close) / rth_high * 100) if rth_high > 0 else 0.0
    rth_range_pct = ((rth_high - rth_low) / rth_open * 100) if rth_open > 0 else 0.0
    day_return_pct = ((rth_close - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

    # HOD/LOD times
    hod_idx = rth_df["high"].idxmax()
    lod_idx = rth_df["low"].idxmin()
    hod_time = str(df_1m.loc[hod_idx, "timestamp"])[:16]
    lod_time = str(df_1m.loc[lod_idx, "timestamp"])[:16]

    # Return percentages at intervals
    def ret_at_min(n):
        target = rth_df[rth_df.index <= rth_df.index[0] + n]
        if target.empty: return 0.0
        return ((float(target["close"].iloc[-1]) - rth_open) / rth_open * 100) if rth_open > 0 else 0.0

    # Close at 15:59
    close_1559_mask = (ts.dt.hour == 15) & (ts.dt.minute == 59)
    close_1559_df = df_1m[close_1559_mask]
    close_1559 = float(close_1559_df["close"].iloc[-1]) if not close_1559_df.empty else rth_close

    eod_volume = int(df_1m["volume"].sum())
    transactions = int(df_1m["transactions"].sum()) if "transactions" in df_1m.columns else 0

    # Overall OHLCV
    overall_open = float(df_1m["open"].iloc[0])
    overall_high = float(df_1m["high"].max())
    overall_low = float(df_1m["low"].min())
    overall_close = float(df_1m["close"].iloc[-1])
    overall_volume = int(df_1m["volume"].sum())

    return {
        "ticker": ticker,
        "timestamp": pd.Timestamp(f"{date_str} 09:30:00"),
        "open": overall_open,
        "high": overall_high,
        "low": overall_low,
        "close": overall_close,
        "volume": overall_volume,
        "transactions": transactions,
        "pm_volume": pm_volume,
        "pm_high": pm_high,
        "pm_low": pm_low,
        "pm_high_time": pm_high_time,
        "pm_low_time": pm_low_time,
        "gap_pct": round(gap_pct, 4),
        "pmh_gap_pct": round(pmh_gap_pct, 4),
        "pmh_fade_pct": round(pmh_fade_pct, 4),
        "rth_volume": rth_volume,
        "rth_open": rth_open,
        "rth_high": rth_high,
        "rth_low": rth_low,
        "rth_close": rth_close,
        "rth_run_pct": round(rth_run_pct, 4),
        "rth_fade_pct": round(rth_fade_pct, 4),
        "rth_range_pct": round(rth_range_pct, 4),
        "hod_time": hod_time,
        "lod_time": lod_time,
        "m15_return_pct": round(ret_at_min(15), 4),
        "m30_return_pct": round(ret_at_min(30), 4),
        "m60_return_pct": round(ret_at_min(60), 4),
        "m180_return_pct": round(ret_at_min(180), 4),
        "close_1559": close_1559,
        "last_close": rth_close,
        "day_return_pct": round(day_return_pct, 4),
        "prev_close": prev_close,
        "eod_volume": eod_volume,
    }

# ─── GCS writer ───────────────────────────────────────

def write_parquet_to_gcs(df: pd.DataFrame, year: int, month: int):
    """Escribe un DataFrame como Parquet a GCS."""
    if df.empty:
        return

    con = duckdb.connect()
    con.execute(f"""
        INSTALL httpfs; LOAD httpfs;
        SET s3_endpoint='storage.googleapis.com';
        SET s3_access_key_id='{GCS_HMAC_KEY}';
        SET s3_secret_access_key='{GCS_HMAC_SECRET}';
        SET s3_url_style='path';
    """)

    df["year"] = year
    df["month"] = month

    path = f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={year}/month={month}/catchup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"

    con.register("df_to_write", df)
    con.execute(f"COPY df_to_write TO '{path}' (FORMAT PARQUET)")
    con.close()
    logger.info(f"  Written {len(df)} rows to {path}")

# ─── Main loop ────────────────────────────────────────

def get_last_gcs_date() -> date:
    """Obtener la última fecha con datos completos en GCS."""
    con = duckdb.connect()
    con.execute(f"""
        INSTALL httpfs; LOAD httpfs;
        SET s3_endpoint='storage.googleapis.com';
        SET s3_access_key_id='{GCS_HMAC_KEY}';
        SET s3_secret_access_key='{GCS_HMAC_SECRET}';
        SET s3_url_style='path';
    """)
    result = con.execute(f"""
        SELECT MAX(CAST(timestamp AS DATE))
        FROM read_parquet('gs://{GCS_BUCKET}/cold_storage/daily_metrics/*/*/*.parquet',
                          hive_partitioning=true)
        WHERE month < 3 OR year < 2026
    """).fetchone()
    con.close()
    return result[0] if result and result[0] else date(2026, 2, 25)

def get_trading_days(start: date, end: date) -> list[str]:
    """Retorna días hábiles entre start y end."""
    days = []
    current = start + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5:  # Lunes-Viernes
            days.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    return days

def process_single_ticker(args):
    """Procesa un ticker para un día dado."""
    ticker, date_str, prev_close = args
    try:
        df_1m = get_1m_bars(ticker, date_str)
        if df_1m.empty:
            return None
        metrics = process_day_metrics(ticker, df_1m, prev_close, date_str)
        return metrics
    except Exception as e:
        logger.warning(f"  {ticker} {date_str}: {e}")
        return None

def main():
    logger.info("=== BTT GCS Catchup Pipeline ===")

    # 1. Determinar rango
    last_date = get_last_gcs_date()
    today = date.today()
    trading_days = get_trading_days(last_date, today)

    logger.info(f"Last GCS date: {last_date}")
    logger.info(f"Today: {today}")
    logger.info(f"Trading days to process: {len(trading_days)}")

    # 2. Mantener prev_closes en memoria
    prev_closes: dict[str, float] = {}

    # 3. Buffer por mes
    monthly_buffer: dict[tuple, list] = {}

    for i, date_str in enumerate(trading_days):
        logger.info(f"\n[{i+1}/{len(trading_days)}] Processing {date_str}...")

        # 3a. Obtener OHLCV diario completo
        daily_results = get_grouped_daily(date_str)
        if not daily_results:
            logger.warning(f"  No data for {date_str}, skipping")
            continue

        logger.info(f"  {len(daily_results)} tickers in market")

        # 3b. Identificar candidatos
        candidates = []
        new_prev_closes = {}

        for item in daily_results:
            t = item.get("T", "")
            o = item.get("o", 0)
            c = item.get("c", 0)

            if not t or o <= 0:
                continue

            new_prev_closes[t] = c

            pc = prev_closes.get(t, 0)
            if pc <= 0:
                continue

            gap = abs((o - pc) / pc * 100)

            if gap >= GAP_PCT_MIN:
                candidates.append((t, date_str, pc))

        logger.info(f"  Candidates (gap >= {GAP_PCT_MIN}%): {len(candidates)}")

        # 3c. Descargar 1m bars en paralelo
        day_metrics = []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(process_single_ticker, args): args
                      for args in candidates}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    day_metrics.append(result)

        logger.info(f"  Processed: {len(day_metrics)} tickers with metrics")

        # 3d. Añadir al buffer mensual
        if day_metrics:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            key = (dt.year, dt.month)
            if key not in monthly_buffer:
                monthly_buffer[key] = []
            monthly_buffer[key].extend(day_metrics)

        # 3e. Actualizar prev_closes
        prev_closes.update(new_prev_closes)

        time.sleep(SLEEP_BETWEEN_DAYS)

    # 4. Escribir Parquets a GCS por mes
    logger.info("\n=== Writing Parquets to GCS ===")
    for (year, month), rows in monthly_buffer.items():
        df = pd.DataFrame(rows)
        logger.info(f"  {year}-{month:02d}: {len(df)} rows")
        write_parquet_to_gcs(df, year, month)

    # 5. Regenerar hot cache
    logger.info("\n=== Regenerating hot cache ===")
    os.system("python scripts/generate_hot_cache_parquet.py")

    logger.info("\n=== Done ===")

if __name__ == "__main__":
    main()
