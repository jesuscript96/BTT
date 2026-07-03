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

# Throttling artificial de FREE TIER (5 req/min). El plan pago de Massive/Polygon
# tiene llamadas ilimitadas (soft-limit ~100 req/s), así que por defecto NO se
# aplica. Poner MASSIVE_THROTTLE_ENABLED=true vuelve al comportamiento free-tier.
MASSIVE_THROTTLE_ENABLED = os.getenv("MASSIVE_THROTTLE_ENABLED", "false") == "true"
# Sleep entre días: SOLO en free tier. En plan pago = 0 (sin throttle artificial).
SLEEP_BETWEEN_DAYS = 0.5 if MASSIVE_THROTTLE_ENABLED else 0.0

# Concurrencia: a MAX_WORKERS=10 con ~200ms/req el pico es ~50 req/s, bajo el
# soft-limit de ~100 req/s recomendado por Massive. Configurable por env; mantener
# <=16 (~80 req/s) para conservar margen de seguridad.
MAX_WORKERS = max(1, int(os.getenv("MASSIVE_MAX_WORKERS", "10")))

# Ajuste por splits en las llamadas a Massive/Polygon. Por defecto **false**
# (precios as-traded, tal como se negociaron ese día). Con adjusted=true, un
# backfill histórico devuelve precios RE-AJUSTADOS por reverse-splits ocurridos
# ENTRE la fecha pedida y hoy (p.ej. HUBC feb-2026 $2.92 -> $2920 = factor 1000x),
# lo que corrompe el lake (que es as-traded). Poner MASSIVE_ADJUSTED=true SOLO para
# casos puntuales y conscientes. El param HTTP debe ir en minúsculas ("true"/
# "false"): un bool de Python se serializaría como "True"/"False" y Polygon lo
# interpretaría mal (cualquier valor != "true" = sin ajuste).
MASSIVE_ADJUSTED = os.getenv("MASSIVE_ADJUSTED", "false").strip().lower() == "true"
_ADJUSTED_PARAM = "true" if MASSIVE_ADJUSTED else "false"

# ─── Massive client ───────────────────────────────────

def _get_with_retry(url: str, params: dict, max_retries: int = 5,
                    backoff: float = 2.0, timeout: int = 15):
    """
    GET con retry ante (a) fallos de red transitorios (SSL handshake, conexión
    cortada, timeout) y (b) HTTP 429 (rate limit), reintentado con backoff
    exponencial (cap 30s). El resto de status no-2xx NO se reintenta — el caller
    decide qué hacer (y debe loguearlo como [ERROR], no descartarlo en silencio).
    Si se agotan los reintentos con un 429 persistente, devuelve esa respuesta 429
    para que el caller la marque como error visible.
    """
    transient = (
        requests.exceptions.SSLError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
    )
    resp = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, verify=False, timeout=timeout)
        except transient as e:
            if attempt == max_retries - 1:
                raise
            wait = backoff * (attempt + 1)
            logger.warning(
                f"  Transient network error on {url.rsplit('/', 2)[-1]} "
                f"(attempt {attempt + 1}/{max_retries}): {type(e).__name__}. "
                f"Retrying in {wait:.1f}s..."
            )
            time.sleep(wait)
            continue
        # Rate limit: reintentar con backoff exponencial (cap 30s).
        if resp.status_code == 429:
            if attempt == max_retries - 1:
                break  # sin más reintentos; el caller maneja el 429 como [ERROR]
            wait_time = min(2 ** attempt, 30)
            logger.warning(
                f"[429] Rate limited en {url.rsplit('/', 2)[-1]}, esperando "
                f"{wait_time}s (intento {attempt + 1}/{max_retries})"
            )
            time.sleep(wait_time)
            continue
        return resp
    return resp


def _to_ny_naive(ms_series):
    """Convierte timestamps Unix-ms de Massive (UTC real) a NY wall-clock naive.

    Massive entrega `t` en UTC-ms (campo t de /v2/aggs, Polygon-compatible). El
    backtester y los masks de sesión (premarket/RTH/AM) asumen NY wall-clock
    naive, así que hay que convertir explícitamente UTC -> America/New_York
    (DST-aware) -> naive. Sin esto, el dato reciente quedaba en UTC y los gaps se
    calculaban contra barras equivocadas (rth_open salía de una barra premarket
    -> gap con signo invertido).

    Guard de invariante: tras convertir, ninguna barra de equity US debe caer
    antes de las 04:00 ET (apertura premarket) ni después de las 20:00 ET. Si se
    viola, Massive cambió su contrato de TZ -> se aborta el batch en vez de
    escribir datos corruptos. Usa min/max de la sesión completa, robusto a
    tickers ilíquidos cuya primera barra es 09:30 (no da falso positivo).
    """
    ny = (
        pd.to_datetime(ms_series, unit="ms")
        .dt.tz_localize("UTC")
        .dt.tz_convert("America/New_York")
        .dt.tz_localize(None)
    )
    if len(ny) > 0:
        hours = ny.dt.hour
        mn, mx = int(hours.min()), int(hours.max())
        if mn < 4 or mx > 20:
            logger.warning(
                f"[TZ GUARD] sesión fuera de rango ET (min_hour={mn}, "
                f"max_hour={mx}; esperado 4-20). ¿Cambió el contrato TZ de "
                f"Massive? No se escribe este batch."
            )
            raise ValueError(
                f"TZ invariant violated: session hours [{mn}..{mx}] outside [4..20] ET"
            )
    return ny


def get_grouped_daily(date_str: str) -> list[dict]:
    """OHLCV diario para todo el mercado en una fecha."""
    url = f"{BASE_URL}/v2/aggs/grouped/locale/us/market/stocks/{date_str}"
    try:
        r = _get_with_retry(url, {"apiKey": API_KEY, "adjusted": _ADJUSTED_PARAM})
    except Exception as e:
        logger.error(f"grouped_daily {date_str} failed after retries: {e}")
        return []
    if r is not None and r.status_code == 200:
        return r.json().get("results", [])
    status = r.status_code if r is not None else "no-response"
    logger.error(f"[ERROR] grouped_daily {date_str}: HTTP {status} — día NO procesado")
    return []

def get_1m_bars(ticker: str, date_str: str) -> pd.DataFrame:
    """Barras de 1 minuto para un ticker en una fecha."""
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}"
    try:
        r = _get_with_retry(url, {"apiKey": API_KEY, "adjusted": _ADJUSTED_PARAM,
                                  "sort": "asc", "limit": 50000})
    except Exception as e:
        logger.error(f"[ERROR] {ticker} {date_str} 1m fetch failed after retries: {e} — datos NO ingeridos")
        return pd.DataFrame()
    if r is None or r.status_code != 200:
        # Visible, NO silencioso: un 429 persistente o cualquier no-200 se loguea
        # con ticker+fecha+status para poder re-fetchear (antes se descartaba mudo,
        # indistinguible de "sin datos ese día").
        status = r.status_code if r is not None else "no-response"
        logger.error(f"[ERROR] {ticker} {date_str} 1m: HTTP {status} — datos NO ingeridos (revisar/re-fetch)")
        return pd.DataFrame()
    results = r.json().get("results", [])
    if not results:
        return pd.DataFrame()
    df = pd.DataFrame(results)
    df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                              "l": "low", "c": "close", "v": "volume",
                              "vw": "vwap", "n": "transactions"})
    df["timestamp"] = _to_ny_naive(df["timestamp"])
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

    # Return percentages at intervals (temporal mask, robust to gaps)
    def ret_at_min(n):
        rth_start = ts[rth_mask].iloc[0] if rth_mask.any() else None
        if rth_start is None: return 0.0
        limit_time = rth_start + pd.Timedelta(minutes=n)
        target = rth_df[ts[rth_mask] <= limit_time]
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
    """Escribe DataFrame a GCS mergeando con datos existentes del mes."""
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

    path = f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={year}/month={month}/catchup_{year}_{month:02d}.parquet"

    # Leer parquet existente si existe y mergear
    try:
        existing = con.execute(f"""
            SELECT * FROM read_parquet('{path}')
        """).fetchdf()

        if not existing.empty:
            # Concat y dedupe — datos nuevos ganan
            df["year"] = year
            df["month"] = month
            n_new = len(df)
            combined = pd.concat([existing, df], ignore_index=True)
            combined = combined.drop_duplicates(
                subset=["ticker", "timestamp"],
                keep="last"
            )
            df = combined
            logger.info(f"  Merged with existing: {len(existing)} + {n_new} new rows = {len(df)} total")
    except Exception:
        # No existe parquet previo — escribir desde cero
        df["year"] = year
        df["month"] = month
        logger.info(f"  No existing parquet for {year}-{month:02d}, writing fresh")

    con.register("df_to_write", df)
    con.execute(f"COPY df_to_write TO '{path}' (FORMAT PARQUET)")
    con.close()
    logger.info(f"  Written {len(df)} rows to {path}")


def write_intraday_to_gcs(df: pd.DataFrame, year: int, month: int, date_str: str):
    """Persiste las barras 1m crudas de un día a cold_storage/intraday_1m.

    Escritura por día (nombre determinista → idempotente, re-runs sobrescriben)
    y sin read-merge: a diferencia de daily_metrics, un mes intraday son ~34M
    filas; leerlo para mergear reventaría memoria (el OOM que apagó el pulse).
    """
    if df is None or df.empty:
        return

    df = df.copy()
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    df["month"] = month
    df["year"] = year
    # Orden EXACTO del schema del intraday_1m existente en GCS.
    df = df[["ticker", "volume", "open", "close", "high", "low",
             "timestamp", "transactions", "date", "month", "year"]]

    con = duckdb.connect()
    con.execute(f"""
        INSTALL httpfs; LOAD httpfs;
        SET s3_endpoint='storage.googleapis.com';
        SET s3_access_key_id='{GCS_HMAC_KEY}';
        SET s3_secret_access_key='{GCS_HMAC_SECRET}';
        SET s3_url_style='path';
    """)

    path = f"gs://{GCS_BUCKET}/cold_storage/intraday_1m/year={year}/month={month}/catchup_intraday_{date_str}.parquet"
    con.register("df_intraday", df)
    # CAST explícito al schema EXACTO del intraday_1m existente: volume BIGINT
    # (la API lo devuelve como float) y timestamp TIMESTAMP en µs (pandas usa ns).
    # Evita deriva de tipos entre particiones viejas y nuevas en el data lake.
    con.execute(f"""
        COPY (
            SELECT ticker,
                   TRY_CAST(volume AS BIGINT) AS volume,
                   open, close, high, low,
                   CAST(timestamp AS TIMESTAMP) AS timestamp,
                   transactions, date, month, year
            FROM df_intraday
        ) TO '{path}' (FORMAT PARQUET)
    """)
    con.close()
    logger.info(f"  Written {len(df)} intraday 1m rows to {path}")

# ─── Main loop ────────────────────────────────────────

CHECKPOINT_PATH = os.path.join(os.path.dirname(__file__), 'catchup_checkpoint.json')


def read_checkpoint() -> Optional[date]:
    """Lee la última fecha exitosa del checkpoint local, si existe."""
    if not os.path.exists(CHECKPOINT_PATH):
        return None
    try:
        with open(CHECKPOINT_PATH, 'r') as f:
            data = json.load(f)
        s = data.get('last_processed_date', '')
        return datetime.strptime(s, '%Y-%m-%d').date() if s else None
    except Exception as e:
        logger.warning(f"Checkpoint read failed: {e}")
        return None


def write_checkpoint(d: date) -> None:
    """Escribe la última fecha procesada al checkpoint local."""
    try:
        with open(CHECKPOINT_PATH, 'w') as f:
            json.dump({'last_processed_date': d.strftime('%Y-%m-%d')}, f)
    except Exception as e:
        logger.warning(f"Checkpoint write failed: {e}")


def get_last_gcs_date() -> date:
    """
    Obtener la última fecha con datos. Usa el máximo entre la fecha
    máxima encontrada en GCS y el checkpoint local — así, si un run
    procesó días dentro del mes actual pero crasheó antes de poder
    escribir su parquet, no se re-procesan los días confirmados.
    """
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
        WHERE ticker IS NOT NULL
    """).fetchone()
    con.close()
    gcs_max = result[0] if result and result[0] else date(2026, 2, 25)

    checkpoint = read_checkpoint()
    if checkpoint and checkpoint > gcs_max:
        logger.info(f"Checkpoint ({checkpoint}) > GCS max ({gcs_max}); resuming from checkpoint")
        return checkpoint
    return gcs_max

def get_trading_days(start: date, end: date) -> list[str]:
    """Retorna días hábiles entre start y end."""
    days = []
    current = start + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5:  # Lunes-Viernes
            days.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    return days


def _seed_prev_closes(seed_date: date) -> dict[str, float]:
    """Lee los closes de seed_date desde GCS para arrancar prev_closes."""
    logger.info(f"Seeding prev_closes from GCS for {seed_date}...")
    try:
        con = duckdb.connect()
        con.execute(f"""
            INSTALL httpfs; LOAD httpfs;
            SET s3_endpoint='storage.googleapis.com';
            SET s3_access_key_id='{GCS_HMAC_KEY}';
            SET s3_secret_access_key='{GCS_HMAC_SECRET}';
            SET s3_url_style='path';
        """)
        r = con.execute(f"""
            SELECT ticker, close
            FROM read_parquet(
                'gs://{GCS_BUCKET}/cold_storage/daily_metrics/*/*/*.parquet',
                hive_partitioning=true
            )
            WHERE CAST(timestamp AS DATE) = DATE '{seed_date.isoformat()}'
              AND close > 0
        """).fetchdf()
        con.close()
        result = dict(zip(r['ticker'], r['close']))
        logger.info(f"Seeded {len(result)} tickers from {seed_date}")
        return result
    except Exception as e:
        logger.warning(f"Could not seed prev_closes: {e}")
        return {}

def process_single_ticker(args):
    """Procesa un ticker para un día dado.

    Devuelve la tupla (metrics, df_1m): las métricas diarias y las barras 1m
    crudas para persistirlas en cold_storage/intraday_1m. (None, None) si falla.
    """
    ticker, date_str, prev_close = args
    try:
        df_1m = get_1m_bars(ticker, date_str)
        if df_1m.empty:
            return (None, None)
        metrics = process_day_metrics(ticker, df_1m, prev_close, date_str)
        return (metrics, df_1m)
    except Exception as e:
        logger.warning(f"  {ticker} {date_str}: {e}")
        return (None, None)

def _flush_month(monthly_buffer: dict, year: int, month: int) -> None:
    """Escribe el buffer de un mes a GCS y lo limpia."""
    rows = monthly_buffer.get((year, month), [])
    if not rows:
        return
    df = pd.DataFrame(rows)
    logger.info(f"=== Flushing {year}-{month:02d}: {len(df)} rows ===")
    write_parquet_to_gcs(df, year, month)
    monthly_buffer.pop((year, month), None)


def main():
    logger.info("=== BTT GCS Catchup Pipeline ===")

    # 1. Determinar rango. INTRADAY_BACKFILL_FROM fuerza el inicio (one-shot)
    # para rellenar intraday_1m, ya que get_last_gcs_date() mira daily_metrics.
    backfill_from = os.getenv("INTRADAY_BACKFILL_FROM")
    if backfill_from:
        last_date = date.fromisoformat(backfill_from)
        logger.info(f"INTRADAY_BACKFILL_FROM set → forcing start at {last_date}")
    else:
        last_date = get_last_gcs_date()

    # Optional end bound (one-shot backfill chunking / reprocessing). Default:
    # today, so the nightly cron (no env) behaves exactly as before. Note
    # get_trading_days is exclusive of last_date and inclusive of end_date.
    backfill_to = os.getenv("INTRADAY_BACKFILL_TO")
    if backfill_to:
        end_date = date.fromisoformat(backfill_to)
        logger.info(f"INTRADAY_BACKFILL_TO set → forcing end at {end_date}")
    else:
        end_date = date.today()
    trading_days = get_trading_days(last_date, end_date)

    logger.info(f"Last GCS date: {last_date}")
    logger.info(f"End date: {end_date}")
    logger.info(f"Trading days to process: {len(trading_days)}")

    # 2. Mantener prev_closes en memoria, sembrados desde GCS
    prev_closes = _seed_prev_closes(last_date)

    # 3. Buffer por mes — se vacía a GCS al detectar cambio de mes
    monthly_buffer: dict[tuple, list] = {}
    prev_month_key: Optional[tuple] = None

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
            h = item.get("h", 0)

            if not t or o <= 0:
                continue

            new_prev_closes[t] = c

            pc = prev_closes.get(t, 0)
            if pc <= 0:
                continue

            gap = abs((o - pc) / pc * 100)
            pm_runner_est = ((h - pc) / pc * 100) if pc > 0 else 0

            if gap >= GAP_PCT_MIN or pm_runner_est >= PM_RUNNER_MIN:
                candidates.append((t, date_str, pc))

        logger.info(f"  Candidates (gap >= {GAP_PCT_MIN}% or pmh est >= {PM_RUNNER_MIN}%): {len(candidates)}")

        # 3c. Descargar 1m bars en paralelo
        day_metrics = []
        day_intraday = []  # frames df_1m del día (para cold_storage/intraday_1m)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(process_single_ticker, args): args
                      for args in candidates}
            for future in as_completed(futures):
                metrics, df_1m = future.result()
                if metrics:
                    day_metrics.append(metrics)
                if df_1m is not None and not df_1m.empty:
                    day_intraday.append(df_1m)

        logger.info(f"  Processed: {len(day_metrics)} tickers with metrics")

        # 3d. Detectar cambio de mes → flush del mes anterior antes de añadir
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        month_key = (dt.year, dt.month)
        if prev_month_key is not None and month_key != prev_month_key:
            _flush_month(monthly_buffer, prev_month_key[0], prev_month_key[1])
        prev_month_key = month_key

        # 3e. Añadir al buffer mensual
        if day_metrics:
            if month_key not in monthly_buffer:
                monthly_buffer[month_key] = []
            monthly_buffer[month_key].extend(day_metrics)

        # 3e-bis. Persistir intraday 1m del día (flush inmediato, memoria acotada)
        if day_intraday:
            day_df = pd.concat(day_intraday, ignore_index=True)
            write_intraday_to_gcs(day_df, dt.year, dt.month, date_str)

        # 3f. Actualizar prev_closes y checkpoint
        prev_closes.update(new_prev_closes)
        write_checkpoint(dt.date())

        # Throttle artificial SOLO en free tier (MASSIVE_THROTTLE_ENABLED=true).
        # En plan pago se omite por completo (sin sleeps innecesarios en el backfill).
        if MASSIVE_THROTTLE_ENABLED:
            time.sleep(SLEEP_BETWEEN_DAYS)

    # 4. Flush del último mes pendiente
    if prev_month_key is not None:
        _flush_month(monthly_buffer, prev_month_key[0], prev_month_key[1])

    # 5. Regenerar hot cache
    logger.info("\n=== Regenerating hot cache ===")
    os.system(f'"{sys.executable}" scripts/generate_hot_cache_parquet.py')

    logger.info("\n=== Done ===")

if __name__ == "__main__":
    main()
