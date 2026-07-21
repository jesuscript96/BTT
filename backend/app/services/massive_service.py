"""Cliente único para la API REST de Massive (Polygon-style).

Centraliza lo que antes estaba repartido entre ticker_analysis.py (news, logo)
y lo que se scrapeaba de Yahoo/Finviz/knowthefloat: overview de ticker, precio,
barras diarias, fundamentales XBRL y short interest oficial FINRA.

Semántica de errores (importa para la caché SWR del router):
  - Fallo de transporte / 5xx / 429 agotado  -> MassiveError (el llamador decide;
    la SWR conserva el stale y NO persiste un payload vacío).
  - 404 / resultados vacíos                  -> None o [] (es "no hay dato",
    p. ej. overview de un ticker deslistado; el llamador aplica su fallback).

Todas las requests van con verificación TLS por defecto (certifi vía requests),
sesión compartida con pool de conexiones y retries idempotentes.
"""

import os
import threading
import time
from datetime import date, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_KEY = os.getenv("MASSIVE_API_KEY", "")
BASE_URL = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")

DEFAULT_TIMEOUT = 6  # segundos por request; las llamadas medidas rondan 0,3-0,7s


class MassiveError(Exception):
    """Fallo de transporte o de servidor hablando con Massive."""


_session = None
_session_lock = threading.Lock()


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                s = requests.Session()
                retry = Retry(
                    total=2,
                    backoff_factor=0.3,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=("GET",),
                )
                adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=retry)
                s.mount("https://", adapter)
                s.mount("http://", adapter)
                _session = s
    return _session


def _get(path: str, params: dict | None = None) -> dict | None:
    """GET a Massive. dict en 200, None en 404, MassiveError en el resto."""
    if not API_KEY:
        raise MassiveError("MASSIVE_API_KEY no configurada")
    p = dict(params or {})
    p["apiKey"] = API_KEY
    try:
        resp = _get_session().get(f"{BASE_URL}{path}", params=p, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as e:
        raise MassiveError(f"transporte {path}: {e}") from e
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise MassiveError(f"HTTP {resp.status_code} en {path}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as e:
        raise MassiveError(f"JSON inválido en {path}") from e


# ── Memo in-process con TTL (los datos de referencia cambian poco) ───────────

_memo: dict = {}
_memo_lock = threading.Lock()


def _memoized(key: str, ttl_seconds: int, fetch):
    now = time.time()
    with _memo_lock:
        hit = _memo.get(key)
        if hit and hit[1] > now:
            return hit[0]
    value = fetch()  # fuera del lock: no serializar llamadas HTTP distintas
    with _memo_lock:
        _memo[key] = (value, now + ttl_seconds)
    return value


# ── Endpoints ────────────────────────────────────────────────────────────────

def get_overview(ticker: str) -> dict | None:
    """/v3/reference/tickers/{t}: perfil + market_cap + shares + CIK + branding.

    Deslistados: el endpoint de detalle devuelve vacío → (1) reintento con
    date=hace 30 días, (2) búsqueda con active=false, que conserva name, CIK,
    exchange y delisted_utc (imprescindible: company_tickers.json de SEC solo
    lista activos, así que este CIK es el único camino a filings/XBRL de un
    deslistado). Cacheado 24h en proceso (lo comparten /{ticker}, /logo e
    insiders vía CIK).
    """
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return None

    def _fetch():
        data = _get(f"/v3/reference/tickers/{ticker}")
        results = (data or {}).get("results") or None
        if not results:
            past = (date.today() - timedelta(days=30)).isoformat()
            data = _get(f"/v3/reference/tickers/{ticker}", {"date": past})
            results = (data or {}).get("results") or None
        if not results:
            data = _get("/v3/reference/tickers", {"ticker": ticker, "active": "false", "limit": 1})
            rows = (data or {}).get("results") or []
            results = rows[0] if rows else None
        return results

    return _memoized(f"overview:{ticker}", 24 * 3600, _fetch)


def get_cik(ticker: str) -> str | None:
    """CIK de 10 dígitos desde el overview (Massive ya lo trae normalizado)."""
    try:
        ov = get_overview(ticker)
    except MassiveError:
        return None
    cik = (ov or {}).get("cik")
    return str(cik).zfill(10) if cik else None


def get_snapshot_price(ticker: str) -> float | None:
    """Precio actual desde /v2/snapshot: lastTrade -> min -> day -> prevDay."""
    ticker = (ticker or "").upper().strip()
    data = _get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
    snap = (data or {}).get("ticker") or {}
    for path in (("lastTrade", "p"), ("min", "c"), ("day", "c"), ("prevDay", "c")):
        node = snap
        for k in path:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        if node:
            try:
                v = float(node)
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
    return None


def get_daily_bars(ticker: str, years: int = 5) -> list[dict]:
    """Barras diarias ajustadas de /v2/aggs (cubre también deslistados).

    Devuelve [{t(ms), o, h, l, c, v}] ascendente; [] si no hay datos.
    """
    ticker = (ticker or "").upper().strip()
    d_to = date.today().isoformat()
    d_from = (date.today() - timedelta(days=365 * years + 5)).isoformat()
    data = _get(
        f"/v2/aggs/ticker/{ticker}/range/1/day/{d_from}/{d_to}",
        {"adjusted": "true", "sort": "asc", "limit": 50000},
    )
    return (data or {}).get("results") or []


def get_minute_bars_for_dates(ticker: str, dates: list[str], minutes: int = 15,
                              max_workers: int = 12) -> list[dict]:
    """Barras de `minutes`-min de fechas concretas vía /v2/aggs, EN PARALELO.

    Para el chart de runner stats, que binéa en tramos de 15 min, pedimos velas
    de 15-min directamente (default): ~26 barras/día en vez de ~390 con 1-min.
    Eso reduce ~30× el JSON a parsear y construir en Python — el verdadero
    cuello bajo el GIL en uvicorn (medido: 40k barras/ticker parseadas en un
    thread de background bajo carga inflaban el chart de ~2 s a ~8 s).

    Devuelve [{date_str, t(ms), o, c}] plano; fechas sin datos o con error
    transitorio se omiten (el chart promedia las que haya).
    """
    from concurrent.futures import ThreadPoolExecutor

    ticker = (ticker or "").upper().strip()
    dates = sorted(set(d for d in dates if d))
    if not ticker or not dates:
        return []

    def _one(d: str) -> list[dict]:
        try:
            data = _get(
                f"/v2/aggs/ticker/{ticker}/range/{minutes}/minute/{d}/{d}",
                {"adjusted": "true", "sort": "asc", "limit": 500},
            )
            return [
                {"date_str": d, "t": r.get("t"), "o": r.get("o"), "c": r.get("c")}
                for r in ((data or {}).get("results") or [])
            ]
        except Exception:  # noqa: BLE001 — una fecha caída no tumba el chart
            return []

    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for rows in ex.map(_one, dates):
            out.extend(rows)
    return out


def get_financials(ticker: str) -> list[dict]:
    """Fundamentales XBRL trimestrales de /vX/reference/financials (asc).

    Cada elemento: {end_date, fiscal_period, fiscal_year, financials: {
    balance_sheet, income_statement, cash_flow_statement, ...}}. Memo 15 min:
    lo consumen /{ticker}, /balance-sheet y el informe de Edgie en ráfaga.
    """
    ticker = (ticker or "").upper().strip()

    def _fetch():
        data = _get(
            "/vX/reference/financials",
            {"ticker": ticker, "timeframe": "quarterly", "limit": 20, "order": "desc"},
        )
        results = (data or {}).get("results") or []
        results.sort(key=lambda r: r.get("end_date") or "")
        return results

    return _memoized(f"financials:{ticker}", 15 * 60, _fetch)


def get_short_interest(ticker: str, limit: int = 12) -> list[dict]:
    """Short interest oficial FINRA (quincenal) de /stocks/v1/short-interest.

    Devuelve [{settlement_date, short_interest, days_to_cover,
    avg_daily_volume}] descendente por fecha de liquidación.
    """
    ticker = (ticker or "").upper().strip()

    def _fetch():
        data = _get("/stocks/v1/short-interest", {"ticker": ticker, "limit": limit})
        results = (data or {}).get("results") or []
        results.sort(key=lambda r: r.get("settlement_date") or "", reverse=True)
        return results

    return _memoized(f"short_interest:{ticker}", 6 * 3600, _fetch)


def get_splits_since(since_date: str, max_pages: int = 30) -> list[dict]:
    """Splits corporativos de TODO el universo con execution_date >= since_date,
    paginando next_url. [{ticker, execution_date, split_from, split_to}].

    Lo consume el filtro de calidad de Market Analysis (Patch v2.1 §01.1) para
    cubrir el tail que la tabla massive.splits del lake pueda llevar de retraso
    (auditado 07-jul-2026: la tabla llegaba a 2026-03-30). Memo 24h. La API
    devuelve también splits con fecha FUTURA (anunciados): se devuelven tal cual
    y es el llamador quien filtra por execution_date <= fecha del gap.
    """
    since = (since_date or "").strip()
    if not since:
        return []

    def _fetch():
        out: list[dict] = []
        data = _get(
            "/v3/reference/splits",
            {"execution_date.gte": since, "limit": 1000, "order": "asc",
             "sort": "execution_date"},
        )
        for _ in range(max_pages):
            results = (data or {}).get("results") or []
            for r in results:
                out.append({
                    "ticker": r.get("ticker"),
                    "execution_date": r.get("execution_date"),
                    "split_from": r.get("split_from"),
                    "split_to": r.get("split_to"),
                })
            next_url = (data or {}).get("next_url")
            if not next_url:
                break
            try:
                resp = _get_session().get(next_url, params={"apiKey": API_KEY}, timeout=DEFAULT_TIMEOUT)
            except requests.RequestException as e:
                raise MassiveError(f"transporte next_url splits: {e}") from e
            if resp.status_code != 200:
                break  # devolver lo acumulado: mejor tail parcial que nada
            data = resp.json()
        return out

    return _memoized(f"splits_since:{since}", 24 * 3600, _fetch)


def get_news(ticker: str, limit: int = 20) -> list[dict]:
    """Noticias con insights de sentiment de /v2/reference/news (desc)."""
    ticker = (ticker or "").upper().strip()
    data = _get("/v2/reference/news", {"ticker": ticker, "limit": limit, "order": "desc"})
    return (data or {}).get("results") or []


def fetch_branding_data_url(url: str) -> str | None:
    """Descarga un asset de branding (requiere apiKey) y lo devuelve como data URL
    base64, para que la key nunca llegue al navegador."""
    if not url:
        return None
    import base64
    try:
        resp = _get_session().get(url, params={"apiKey": API_KEY}, timeout=DEFAULT_TIMEOUT)
        if not resp.ok:
            return None
        ct = resp.headers.get("content-type", "image/png")
        return f"data:{ct};base64,{base64.b64encode(resp.content).decode()}"
    except requests.RequestException:
        return None


def financial_value(period: dict, statement: str, field: str) -> float | None:
    """Extrae financials[statement][field].value de un periodo, None-safe."""
    try:
        v = (((period or {}).get("financials") or {}).get(statement) or {}).get(field) or {}
        val = v.get("value")
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None
