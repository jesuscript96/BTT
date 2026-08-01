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

# FULL-MARKET: descargar el intraday de TODOS los tickers del día, no solo de los
# candidatos de gap. El filtro de candidatos abarata el cron diario, pero deja
# daily_metrics con ~800 tickers/día en vez de ~12.000, y sus campos derivados de
# intraday (pm_high, rth_run_pct, m15..m180) solo existen para quien se descargó.
# Los años "buenos" (2022 → 2026-02) son full-market porque vinieron del volcado
# masivo original, NO de este script. Cualquier mes que este script rellene solo
# quedará full-market si se corre con FULL_MARKET_ENABLED=true.
# Cuesta ~12.000 req/día en vez de ~600 (≈5 min de reloj). El cron diario lo lleva
# ACTIVADO desde 2026-07-14 (se pasa por -e en el crontab del host); el defecto sigue
# en false para no cambiar el comportamiento de quien lo invoque a mano.
FULL_MARKET_ENABLED = os.getenv("FULL_MARKET_ENABLED", "false").strip().lower() == "true"

# Sesiones hacia atrás que se leen para sembrar prev_closes. Ver _seed_prev_closes.
SEED_LOOKBACK_SESSIONS = int(os.getenv("SEED_LOOKBACK_SESSIONS", "5"))

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

# ─── Missprint (bad-tick) — reconstrucción de vela completa NBBO, gated OFF ───
# Los aggregates 1m de Polygon incluyen prints fuera del NBBO (bad-ticks), sobre
# todo en horario extendido (premarket). NO corrompen SOLO high/low: la vela
# ENTERA (open/close incluidos) queda envenenada — validado con ticks reales el
# 2026-07-15 (GTBP 2025-01-13 close LAKE 4.10 vs real NBBO 2.19, +87%). Y premarket
# es la sesión MÁS usada (Jaume 2026-07-03). Una estrategia que entra por "Bar
# Close Crosses VWAP" pisa el CIERRE phantom (y el VWAP, que se calcula sobre
# H+L+C, también queda envenenado) → entrada/stop falsos.
#
# Por eso NO se recorta la mecha: se SUSTITUYE la vela completa (O/H/L/C) por la
# reconstruida desde los trades dentro del NBBO vigente del minuto (/v3/trades +
# /v3/quotes): open=primer trade válido, close=último, high/low=max/min. La
# detección es RELATIVA (desviación de CUALQUIER campo vs la mediana móvil centrada
# del close), no un umbral fijo de mecha que se dejaba fuera los pequeños. Multipasada:
# la mediana se limpia entre pasadas → caza clusters de barras malas consecutivas.
# Fallback si no hay NBBO: copiar la vela anterior (petición de Jaume). Conservador:
# solo pide NBBO para las barras flagged (raras), best-effort (sin NBBO deja intacta),
# y solo sustituye si el cambio supera MIN_CLIP (no toca barras reales volátiles que
# se reconstruyen a sí mismas). Coste 0 si desactivado. Activar con
# MISSPRINT_CLIP_ENABLED=true tras validar. Ver memoria btt-missprint-analysis
# (forense Jaume 2026-07-15) + btt-motor-v2-merged.
MISSPRINT_CLIP_ENABLED = os.getenv("MISSPRINT_CLIP_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
MISSPRINT_DEV_PCT = float(os.getenv("MISSPRINT_DEV_PCT", "0.10"))      # flag si CUALQUIER campo O/H/L/C se desvía >10% de la mediana móvil
MISSPRINT_NBBO_TOL = float(os.getenv("MISSPRINT_NBBO_TOL", "0.10"))    # trade válido dentro de [bid*0.9, ask*1.1]
MISSPRINT_MIN_PRICE = float(os.getenv("MISSPRINT_MIN_PRICE", "1.0"))   # ignora sub-$1 (ruido de baja liquidez)
MISSPRINT_CTX_WIN = int(os.getenv("MISSPRINT_CTX_WIN", "15"))          # ventana de la mediana móvil (barras)
MISSPRINT_MIN_CLIP = float(os.getenv("MISSPRINT_MIN_CLIP", "0.02"))    # solo sustituir si algún campo cambia > 2%
MISSPRINT_MAX_PASSES = int(os.getenv("MISSPRINT_MAX_PASSES", "3"))     # pasadas anti-cluster (la mediana se limpia entre pasadas)
# Lead-in de quotes: se piden desde N min ANTES del minuto de interés para que los
# primeros trades del minuto tengan quote previo con el que validar (merge_asof
# backward). Sin él, el open reconstruido se sesga (los 1ros trades quedan sin NBBO
# y se caen). Hace que el path per-bar (ingesta) coincida con el windowed (backfill).
MISSPRINT_QUOTE_LEAD_NS = int(os.getenv("MISSPRINT_QUOTE_LEAD_MIN", "15")) * 60_000_000_000

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


def _ny_naive_to_utc_ns(ts) -> int:
    """NY wall-clock naive -> epoch ns UTC (para los timestamp.* de los /v3)."""
    return int(pd.Timestamp(ts).tz_localize("America/New_York").tz_convert("UTC").value)


def _polygon_results(url: str, params: dict, max_retries: int = 4,
                     sleep_s: float = 1.0) -> Optional[list]:
    """GET a un endpoint /v3 (trades/quotes) que devuelve 200 con 'results' vacío
    bajo ráfaga. Reintenta serial (con sleep) ante 200-vacío y errores de red;
    None si se agota sin datos. El sleep NO se paga en el caso común (hay datos al
    primer intento). Respeta el soft-limit al ir serial dentro de cada barra."""
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params={**params, "apiKey": API_KEY},
                             verify=False, timeout=30)
        except Exception:
            time.sleep(sleep_s)
            continue
        if r.status_code == 200:
            res = r.json().get("results", [])
            if res:
                return res
        time.sleep(sleep_s)
    return None


class PolygonFetchError(RuntimeError):
    """No se pudieron leer los ticks (red, 429/5xx, o cuerpo truncado). Distinto de
    'Polygon no tiene ticks': ante ESTO el caller NO debe reconstruir ni aplicar el
    fallback, porque un tramo parcial de quotes da un NBBO falso y una vela
    'corregida' peor que la original. Se deja el dato intacto y se reintenta."""


def _polygon_paginated(url: str, ns_gte: int, ns_lt: int,
                       max_pages: int = 40, retries_empty: int = 3,
                       retries_page: int = 4) -> list:
    """Trae TODOS los results de un endpoint /v3 en [ns_gte, ns_lt) siguiendo
    next_url (Polygon pagina a 50000). Serial con sleep para respetar el soft-limit.
    Reintenta la 1ª página ante 200-vacío (ráfaga). Lista (posiblemente vacía).

    Cada página se reintenta ante red caída, 429/5xx y cuerpo truncado (Polygon
    corta el JSON a media respuesta bajo carga: visto a 421 KB el 2026-07-16).
    Si tras retries_page sigue sin poder leerse, lanza PolygonFetchError en vez de
    devolver el tramo parcial: devolver menos quotes de las reales no se distingue
    de 'no hay quotes' y acabaría fabricando velas. Un 4xx definitivo (404 ticker
    inexistente) sí es 'no hay datos' y devuelve lo acumulado."""
    params = {"timestamp.gte": ns_gte, "timestamp.lt": ns_lt, "limit": 50000,
              "order": "asc", "sort": "timestamp", "apiKey": API_KEY}
    out: list = []
    next_url, use_params, empty_tries = url, params, 0
    for _ in range(max_pages):
        payload = None
        for attempt in range(retries_page):
            try:
                r = requests.get(next_url, params=use_params, verify=False, timeout=40)
            except Exception:
                time.sleep(1.0 * (attempt + 1))
                continue
            if r.status_code == 200:
                try:
                    payload = r.json()
                    break
                except ValueError:      # cuerpo truncado/corrupto: reintentar la MISMA página
                    time.sleep(1.0 * (attempt + 1))
                    continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2.0 * (attempt + 1))
                continue
            return out                  # 4xx definitivo: Polygon no tiene esto, no es fallo
        if payload is None:
            raise PolygonFetchError(f"página irrecuperable tras {retries_page} intentos: "
                                    f"{url.rsplit('/', 1)[-1]}")
        res = payload.get("results", [])
        if not res and not out:
            empty_tries += 1
            if empty_tries >= retries_empty:
                break
            time.sleep(1.0)
            continue
        out.extend(res)
        nxt = payload.get("next_url")
        if not nxt or not res:
            break
        next_url, use_params = nxt, {"apiKey": API_KEY}  # next_url ya lleva cursor+filtros
        time.sleep(0.2)
    return out


def _valid_nbbo_trades(trades: list, quotes: list) -> Optional[pd.DataFrame]:
    """merge_asof trade↔quote vigente, deja solo trades dentro del NBBO. None si nada."""
    if not trades or not quotes:
        return None
    try:
        dt = pd.DataFrame(trades)[["price", "sip_timestamp"]].sort_values("sip_timestamp")
        dq = (pd.DataFrame(quotes)[["bid_price", "ask_price", "sip_timestamp"]]
              .sort_values("sip_timestamp"))
        m = pd.merge_asof(dt, dq, on="sip_timestamp", direction="backward").dropna(
            subset=["bid_price", "ask_price"])
        m = m[(m["bid_price"] > 0) & (m["ask_price"] > 0)]
        ok = m[(m["price"] <= m["ask_price"] * (1 + MISSPRINT_NBBO_TOL)) &
               (m["price"] >= m["bid_price"] * (1 - MISSPRINT_NBBO_TOL))]
    except Exception:
        return None
    return ok if not ok.empty else None


def _fetch_day_nbbo_window(ticker: str, ts_start, ts_end) -> dict:
    """WINDOWED: una sola pasada (paginada) de trades+quotes para [ts_start, ts_end)
    y reconstruye O/H/L/C por minuto desde trades NBBO-válidos. Devuelve
    {minute_ts_naive_ny: {open,high,low,close}}; {} si no hay datos. Reemplaza N
    llamadas por-barra por 2 (+ páginas) por ticker-día — para el backfill masivo."""
    ns0 = _ny_naive_to_utc_ns(ts_start)
    ns1 = _ny_naive_to_utc_ns(ts_end)
    trades = _polygon_paginated(f"{BASE_URL}/v3/trades/{ticker}", ns0, ns1)
    # quotes con lead-in: contexto NBBO para los primeros trades del inicio de la ventana
    quotes = _polygon_paginated(f"{BASE_URL}/v3/quotes/{ticker}", ns0 - MISSPRINT_QUOTE_LEAD_NS, ns1)
    ok = _valid_nbbo_trades(trades, quotes)
    if ok is None:
        return {}
    ny = (pd.to_datetime(ok["sip_timestamp"], unit="ns", utc=True)
          .dt.tz_convert("America/New_York").dt.tz_localize(None))
    ok = ok.assign(_minute=ny.dt.floor("min"))
    cache = {}
    for minute, g in ok.groupby("_minute"):
        p = g["price"].to_numpy(dtype="float64")
        cache[pd.Timestamp(minute)] = {"open": float(p[0]), "high": float(p.max()),
                                       "low": float(p.min()), "close": float(p[-1])}
    return cache


def _reconstruct_bar_from_nbbo(ticker: str, ts, day_cache: Optional[dict] = None) -> Optional[dict]:
    """Reconstruye O/H/L/C de un minuto desde SOLO los trades dentro del NBBO
    vigente. open=primer trade válido, close=último, high/low=max/min. Verdad de
    terreno, sin umbrales. Si `day_cache` (de _fetch_day_nbbo_window) se pasa, lo
    consulta sin red (path backfill windowed); si no, hace la llamada por-barra
    (path ingesta nightly). None si no hay NBBO o ningún trade válido → el caller
    decide el fallback (nunca corrompe por no poder validar)."""
    if day_cache is not None:
        return day_cache.get(pd.Timestamp(ts))
    ns0 = _ny_naive_to_utc_ns(ts)
    tbase = {"timestamp.gte": ns0, "timestamp.lt": ns0 + 60_000_000_000,
             "limit": 50000, "order": "asc", "sort": "timestamp"}
    # quotes con lead-in (ns0 - LEAD): contexto NBBO para los 1ros trades del minuto,
    # si no el open reconstruido se sesga. Iguala este path (ingesta) al windowed (backfill).
    qbase = {"timestamp.gte": ns0 - MISSPRINT_QUOTE_LEAD_NS, "timestamp.lt": ns0 + 60_000_000_000,
             "limit": 50000, "order": "asc", "sort": "timestamp"}
    trades = _polygon_results(f"{BASE_URL}/v3/trades/{ticker}", tbase)
    quotes = _polygon_results(f"{BASE_URL}/v3/quotes/{ticker}", qbase)
    ok = _valid_nbbo_trades(trades, quotes)
    if ok is None:
        return None
    p = ok["price"].to_numpy(dtype="float64")
    return {"open": float(p[0]), "high": float(p.max()),
            "low": float(p.min()), "close": float(p[-1])}


def _flag_missprint_bars(df: pd.DataFrame) -> np.ndarray:
    """Detector RELATIVO: máscara booleana de barras cuya O/H/L/C se desvía
    >MISSPRINT_DEV_PCT de la mediana móvil centrada del close (referencia local
    robusta). Favorece recall (sobre-marcar es inofensivo: una barra real se
    reconstruye a sí misma). Único punto de verdad de la detección — lo comparten
    la ingesta y el backfill para que se comporten idéntico."""
    o = df["open"].to_numpy(dtype="float64")
    h = df["high"].to_numpy(dtype="float64")
    l = df["low"].to_numpy(dtype="float64")
    c = df["close"].to_numpy(dtype="float64")
    med = (df["close"].rolling(MISSPRINT_CTX_WIN, center=True, min_periods=1)
           .median().to_numpy(dtype="float64"))
    med = np.where(med > 0, med, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        dev = np.maximum.reduce([np.abs(o - med), np.abs(h - med),
                                 np.abs(l - med), np.abs(c - med)]) / med
    return np.isfinite(med) & (med >= MISSPRINT_MIN_PRICE) & (dev > MISSPRINT_DEV_PCT)


def _detect_and_clip_missprints(ticker: str, df_1m: pd.DataFrame,
                                day_cache: Optional[dict] = None):
    """Detecta barras con bad-ticks (desviación anómala de CUALQUIER campo O/H/L/C
    vs la mediana móvil centrada del close) y SUSTITUYE la vela COMPLETA por la
    reconstruida desde trades NBBO-válidos. A diferencia del clip antiguo (que solo
    recortaba high/low), corrige open/close — donde vive el daño real: una estrategia
    que entra por 'Bar Close Crosses VWAP' pisa el cierre phantom (forense con ticks
    2026-07-15: GTBP close 4.10 vs real 2.19). Multipasada: la mediana se limpia entre
    pasadas → caza clusters de barras malas consecutivas. Fallback si no hay NBBO:
    copiar la vela anterior (petición de Jaume). Solo sustituye si algún campo cambia
    > MISSPRINT_MIN_CLIP (no toca barras reales volátiles que se reconstruyen a sí
    mismas). Devuelve (df posiblemente modificado, nº de velas sustituidas). No-op
    (coste 0) si MISSPRINT_CLIP_ENABLED=false. Best-effort: sin NBBO deja intacta."""
    if not MISSPRINT_CLIP_ENABLED or df_1m.empty or len(df_1m) < 3:
        return df_1m, 0

    df = df_1m.reset_index(drop=True).copy()
    ts_col = df["timestamp"]
    seen: dict = {}   # idx -> rec | None  (cache: no re-pedir NBBO entre pasadas)
    n_sub = 0

    for _pass in range(MISSPRINT_MAX_PASSES):
        o = df["open"].to_numpy(dtype="float64")
        h = df["high"].to_numpy(dtype="float64")
        l = df["low"].to_numpy(dtype="float64")
        c = df["close"].to_numpy(dtype="float64")
        # Detector relativo compartido con el backfill (mediana móvil centrada del
        # close, robusta a outliers/clusters — se re-limpia entre pasadas).
        flag = _flag_missprint_bars(df)
        idx = [int(i) for i in np.where(flag)[0] if int(i) not in seen]
        if not idx:
            break
        for i in idx:
            rec = _reconstruct_bar_from_nbbo(ticker, ts_col.iloc[i], day_cache)
            seen[i] = rec
            if rec is None:
                # fallback: copiar la vela anterior (ya limpia por orden temporal)
                if i > 0:
                    for f in ("open", "high", "low", "close"):
                        df.at[i, f] = float(df.at[i - 1, f])
                    n_sub += 1
                continue
            # sustituir la vela COMPLETA solo si difiere materialmente (evita churn
            # en barras reales volátiles que se reconstruyen a sí mismas)
            old = {"open": o[i], "high": h[i], "low": l[i], "close": c[i]}
            material = any(
                old[f] > 0 and abs(rec[f] - old[f]) / old[f] > MISSPRINT_MIN_CLIP
                for f in ("open", "high", "low", "close")
            )
            if material:
                for f in ("open", "high", "low", "close"):
                    df.at[i, f] = rec[f]
                n_sub += 1
    if n_sub:
        logger.info(f"  [MISSPRINT] {ticker}: reconstruidas {n_sub} vela(s) bad-tick")
    return df, n_sub

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
    """Cierres de seed_date para arrancar prev_closes, tomados de grouped-daily.

    La fuente es Massive y NO nuestra tabla a propósito: un ticker sin cierre previo
    se descarta (`if pc <= 0: continue`), así que sembrar desde `daily_metrics` pone
    como techo del día lo que ya teníamos ayer. En un run de varios días no se nota
    (a partir del día 2 los cierres salen de grouped-daily), pero el cron procesa UN
    día por ejecución y entonces la tabla se come a sí misma: cada noche entran solo
    los tickers de la noche anterior, menos los que se caigan. Medido el 2026-07-13:
    91,0% de cobertura y bajando, con techo real 98,3% al sembrar desde Massive.

    Se miran SEED_LOOKBACK_SESSIONS sesiones, no solo la última, porque el cierre previo
    de un ticker que no cotizó ayer es el de la última sesión en que sí lo hizo. Un run de
    varios días ya lo hacía sin querer (arrastra los cierres en memoria); el cron de un día
    no, y por eso se dejaba fuera a los tickers que se saltan una sesión. Medido sobre
    2026-07-13: 1 sesión → 98,3% de techo, 5 → 99,7% (a partir de ahí es calderilla).
    """
    logger.info(f"Seeding prev_closes from grouped-daily (hasta {seed_date})...")
    closes: dict[str, float] = {}
    sesiones = 0
    dia = seed_date
    # Se cuentan sesiones CON datos, no días de calendario: los festivos no gastan cupo.
    while sesiones < SEED_LOOKBACK_SESSIONS and (seed_date - dia).days <= 20:
        if dia.weekday() < 5:
            rows = get_grouped_daily(dia.isoformat())
            if rows:
                sesiones += 1
                for r in rows:
                    t, c = r.get("T"), r.get("c", 0)
                    # setdefault: se recorre de la sesión más reciente hacia atrás,
                    # así que el primer cierre que se ve para un ticker es el bueno.
                    if t and c > 0:
                        closes.setdefault(t, c)
        dia -= timedelta(days=1)

    if closes:
        logger.info(f"Seeded {len(closes)} tickers de {sesiones} sesiones (grouped-daily)")
        return closes

    logger.warning("grouped-daily no dio cierres; cayendo al lake (techo más bajo)")
    return _seed_prev_closes_from_lake(seed_date)


def _seed_prev_closes_from_lake(seed_date: date) -> dict[str, float]:
    """Respaldo: lee los closes de seed_date desde GCS."""
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
        # Clip de bad-ticks NBBO-based ANTES de métricas y persistencia, para que
        # tanto las daily_metrics como el intradía que se guarda nazcan limpios.
        # No-op si MISSPRINT_CLIP_ENABLED=false.
        df_1m, _ = _detect_and_clip_missprints(ticker, df_1m)
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

            if FULL_MARKET_ENABLED or gap >= GAP_PCT_MIN or pm_runner_est >= PM_RUNNER_MIN:
                candidates.append((t, date_str, pc))

        if FULL_MARKET_ENABLED:
            logger.info(f"  FULL-MARKET: {len(candidates)} tickers (sin filtro de gap)")
        else:
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

    # 6. Derivado Market Analysis (Patch v2.1): splits frescos vía API + ma_daily
    # (m0/m90/max_spike_5m) + curvas MA-04 de los meses tocados en este run.
    # Best-effort: un fallo aquí NO invalida la ingesta (el servicio hace fail-open).
    if os.getenv("MA_DERIVED_ENABLED", "true").strip().lower() == "true" and trading_days:
        logger.info("\n=== MA derived (splits + ma_daily + curvas) ===")
        try:
            from backfill_ma_derived import refresh_splits_from_api, run_backfill
            refresh_splits_from_api()
            months = sorted({(datetime.strptime(d, '%Y-%m-%d').year,
                              datetime.strptime(d, '%Y-%m-%d').month) for d in trading_days})
            run_backfill(months[0], months[-1], with_curves=True)
        except Exception as e:
            logger.warning(f"MA derived step failed (no bloquea la ingesta): {e}")

    # 7. Tabla de sector (Gaps by Sector): enriquece solo los tickers nuevos del día
    # (los que no estén ya en ticker_sector.parquet). Best-effort. --days 5 cubre el
    # nuevo universo sin re-escanear el histórico.
    if os.getenv("MA_SECTOR_ENABLED", "true").strip().lower() == "true" and trading_days:
        logger.info("\n=== Ticker sector (Gaps by Sector) ===")
        try:
            from build_ticker_sector import build as build_sector
            from datetime import timezone as _tz
            build_sector(min_gap=20.0, days=10, workers=12, refresh_all=False,
                         now_iso=datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        except Exception as e:
            logger.warning(f"Ticker sector step failed (no bloquea la ingesta): {e}")

    logger.info("\n=== Done ===")

if __name__ == "__main__":
    main()
