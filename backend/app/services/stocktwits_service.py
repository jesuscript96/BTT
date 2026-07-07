"""
Servicio de integración con la API oficial de Stocktwits.

Centraliza TODA la comunicación con Stocktwits en el backend (nunca en el
cliente) para:
  1. Proteger las credenciales (Basic Auth vía variables de entorno).
  2. Cumplir los rate limits con una caché Stale-While-Revalidate (SWR) sobre
     `users.duckdb` (tabla `ticker_analysis_cache`, reutilizando el patrón de
     `app/routers/ticker_analysis.py`).
  3. Sanear el payload (recorte de HTML, filtro anti-spam/bots) y mapearlo al
     contrato de `docs/stocktwits-integration/03_CONTRATO_DATOS.md`.

Resiliencia: si Stocktwits cae o las credenciales faltan, se devuelve la última
copia cacheada (aunque esté obsoleta) y, si no existe, un payload vacío válido.
Los errores tipados (404/429/503) solo se propagan cuando NO hay caché previa.

Sin secretos en el repo: las credenciales se leen de `STOCKTWITS_API_KEY` y
`STOCKTWITS_API_SECRET`. Nunca se commitean ni se exponen al frontend.
"""
import os
import re
import html
import json
import threading
from datetime import datetime, timedelta, timezone

# Garantiza que backend/.env esté cargado antes de leer la configuración, sin
# depender del orden de importación de otros módulos.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Configuración (defaults técnicos reversibles — ver 07_DECISIONES_ABIERTAS.md)
#
# Soporta DOS proveedores con el mismo contrato de salida:
#   1. RapidAPI (stocktwits.p.rapidapi.com) — auth por headers x-rapidapi-*.
#      Solo expone el stream por símbolo (/streams/symbol/{symbol}.json), así que
#      sentiment, "why trending" y el radar se DERIVAN de ese stream.
#   2. API oficial (api-gw-prd.stocktwits.com) — Basic Auth, endpoints dedicados.
# El proveedor se autodetecta por la presencia de la clave de RapidAPI.
# ─────────────────────────────────────────────────────────────────────────────
STOCKTWITS_RAPIDAPI_KEY = os.getenv("STOCKTWITS_RAPIDAPI_KEY", "") or os.getenv("RAPIDAPI_KEY", "")
STOCKTWITS_RAPIDAPI_HOST = os.getenv("STOCKTWITS_RAPIDAPI_HOST", "stocktwits.p.rapidapi.com")

# Basic Auth de la API oficial (alternativa a RapidAPI).
STOCKTWITS_API_KEY = os.getenv("STOCKTWITS_API_KEY", "")
STOCKTWITS_API_SECRET = os.getenv("STOCKTWITS_API_SECRET", "")

_DEFAULT_BASE = (
    f"https://{STOCKTWITS_RAPIDAPI_HOST}" if STOCKTWITS_RAPIDAPI_KEY
    else "https://api-gw-prd.stocktwits.com"
)
STOCKTWITS_BASE_URL = os.getenv("STOCKTWITS_BASE_URL", _DEFAULT_BASE)


def _is_rapidapi() -> bool:
    return bool(STOCKTWITS_RAPIDAPI_KEY)

# Anti-spam (small caps sufren pump & dump): umbral de likes y máx. de tickers.
MIN_LIKES_THRESHOLD = int(os.getenv("STOCKTWITS_MIN_LIKES", "2"))
MAX_TICKERS_PER_MESSAGE = int(os.getenv("STOCKTWITS_MAX_TICKERS", "3"))

# Filtro de producto: solo small caps (< $2,000M USD de capitalización).
SMALL_CAP_MAX_USD_MILLIONS = float(os.getenv("STOCKTWITS_SMALL_CAP_MAX_M", "2000"))

# TTLs de caché SWR.
TTL_TRENDING = timedelta(minutes=int(os.getenv("STOCKTWITS_TTL_TRENDING_MIN", "3")))
TTL_SENTIMENT = timedelta(minutes=int(os.getenv("STOCKTWITS_TTL_SENTIMENT_MIN", "5")))
TTL_SUMMARY = timedelta(minutes=int(os.getenv("STOCKTWITS_TTL_SUMMARY_MIN", "10")))
TTL_STREAM = timedelta(minutes=int(os.getenv("STOCKTWITS_TTL_STREAM_MIN", "3")))
TTL_NEWSLETTER = timedelta(minutes=int(os.getenv("STOCKTWITS_TTL_NEWSLETTER_MIN", "30")))

# Claves de caché (reusan ticker_analysis_cache: (ticker, endpoint) PK).
KEY_TRENDING = "TRENDING_SMALL_CAPS"
KEY_NEWSLETTER = "NEWSLETTER_RSS"
ENDPOINT_TRENDING = "social_trending"
ENDPOINT_SUMMARY = "social_summary"
ENDPOINT_SENTIMENT = "social_sentiment"
ENDPOINT_STREAM = "social_stream"
ENDPOINT_NEWSLETTER = "social_newsletter"

# Rutas de la API (cambian según el proveedor). En RapidAPI la única fuente es el
# stream por símbolo; sentiment/summary apuntan también a él y se derivan.
if _is_rapidapi():
    _STREAM_DEFAULT = "/streams/symbol/{symbol}.json"
    PATH_TRENDING = os.getenv("STOCKTWITS_PATH_TRENDING", "")  # no existe → radar derivado
    PATH_STREAM = os.getenv("STOCKTWITS_PATH_STREAM", _STREAM_DEFAULT)
    PATH_SENTIMENT = os.getenv("STOCKTWITS_PATH_SENTIMENT", _STREAM_DEFAULT)
    PATH_SUMMARY = os.getenv("STOCKTWITS_PATH_SUMMARY", _STREAM_DEFAULT)
    PATH_NEWSLETTER = os.getenv("STOCKTWITS_PATH_NEWSLETTER", "")  # sin RSS en RapidAPI
else:
    PATH_TRENDING = os.getenv("STOCKTWITS_PATH_TRENDING", "/symbols_enhanced.json")
    PATH_SUMMARY = os.getenv("STOCKTWITS_PATH_SUMMARY", "/symbols/trending/{symbol}.json")
    PATH_SENTIMENT = os.getenv("STOCKTWITS_PATH_SENTIMENT", "/sentiment/v2/{symbol}/detail")
    PATH_STREAM = os.getenv("STOCKTWITS_PATH_STREAM", "/trending_messages/symbol/{symbol}")
    PATH_NEWSLETTER = os.getenv("STOCKTWITS_PATH_NEWSLETTER", "/news/v2/newsletter/rss")

# Universo del Radar de Momentum (small caps activas socialmente). RapidAPI no
# expone un endpoint de trending, así que el radar se construye sondeando estos
# símbolos y rankeándolos por velocidad social. Configurable por entorno.
_RADAR_DEFAULT = (
    "SOUN,BBAI,RGTI,QBTS,LUNR,ACHR,CHPT,PLUG,FFAI,NVAX,KOSS,GME,AMC,NMAX,RKLB"
)
RADAR_TICKERS = [
    t.strip().upper() for t in os.getenv("STOCKTWITS_RADAR_TICKERS", _RADAR_DEFAULT).split(",")
    if t.strip()
]
RADAR_MAX_CANDIDATES = int(os.getenv("STOCKTWITS_RADAR_MAX", "14"))

DEFAULT_STREAM_LIMIT = 15
MAX_STREAM_LIMIT = 50
STREAM_FETCH_LIMIT = 30  # cuántos mensajes pedimos al stream para derivar métricas


# ─────────────────────────────────────────────────────────────────────────────
# Errores tipados (mapeados a códigos HTTP en el router social)
# ─────────────────────────────────────────────────────────────────────────────
class StocktwitsError(Exception):
    """Error base de comunicación con Stocktwits."""


class TickerNotFound(StocktwitsError):
    """El ticker no existe en Stocktwits → 404 TICKER_NOT_FOUND."""


class RateLimited(StocktwitsError):
    """Rate limit agotado y sin caché → 429 RATE_LIMIT_EXCEEDED."""


class ApiUnavailable(StocktwitsError):
    """Stocktwits caído o sin credenciales → 503 STOCKTWITS_API_UNAVAILABLE."""


# ─────────────────────────────────────────────────────────────────────────────
# Capa HTTP de bajo nivel (única superficie de red; se mockea en los tests)
# ─────────────────────────────────────────────────────────────────────────────
def _has_credentials() -> bool:
    return bool(STOCKTWITS_RAPIDAPI_KEY) or bool(STOCKTWITS_API_KEY and STOCKTWITS_API_SECRET)


# User-Agent de navegador: el upstream de Stocktwits está tras Cloudflare, que
# bloquea el UA por defecto de python-requests con un reto 403 "Just a moment".
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _request_kwargs() -> dict:
    """Devuelve los kwargs de auth/headers para requests según el proveedor."""
    headers = {"User-Agent": _BROWSER_UA, "Accept": "application/json"}
    if STOCKTWITS_RAPIDAPI_KEY:
        headers["x-rapidapi-key"] = STOCKTWITS_RAPIDAPI_KEY
        headers["x-rapidapi-host"] = STOCKTWITS_RAPIDAPI_HOST
        return {"headers": headers}
    from requests.auth import HTTPBasicAuth
    return {"auth": HTTPBasicAuth(STOCKTWITS_API_KEY, STOCKTWITS_API_SECRET), "headers": headers}


def _build_url(path: str) -> str:
    if path.startswith("http"):
        return path
    return f"{STOCKTWITS_BASE_URL.rstrip('/')}{path}"


def _raise_for_status(status_code: int, symbol: str | None = None) -> None:
    if status_code == 404:
        raise TickerNotFound(f"Ticker not found on Stocktwits: {symbol or ''}".strip())
    if status_code == 429:
        raise RateLimited("Stocktwits rate limit exceeded")
    if status_code in (500, 502, 503, 504):
        raise ApiUnavailable(f"Stocktwits API unavailable (HTTP {status_code})")


def _http_get_json(path: str, params: dict | None = None, symbol: str | None = None, timeout: float = 8.0):
    """GET autenticado que devuelve JSON. Lanza errores tipados por status."""
    if not _has_credentials():
        raise ApiUnavailable("Missing Stocktwits credentials")
    if not path:
        raise ApiUnavailable("Endpoint not available for this provider")

    import requests
    resp = requests.get(_build_url(path), params=params, timeout=timeout, **_request_kwargs())
    _raise_for_status(resp.status_code, symbol)
    resp.raise_for_status()
    return resp.json()


def _http_get_text(path: str, params: dict | None = None, timeout: float = 8.0) -> str:
    """GET autenticado que devuelve texto crudo (RSS)."""
    if not _has_credentials():
        raise ApiUnavailable("Missing Stocktwits credentials")
    if not path:
        raise ApiUnavailable("Endpoint not available for this provider")

    import requests
    resp = requests.get(_build_url(path), params=params, timeout=timeout, **_request_kwargs())
    _raise_for_status(resp.status_code)
    resp.raise_for_status()
    return resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de mapeo / saneo
# ─────────────────────────────────────────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    no_tags = _TAG_RE.sub(" ", text)
    unescaped = html.unescape(no_tags)
    return _WS_RE.sub(" ", unescaped).strip()


def _extract_charts(html_text: str | None) -> list:
    if not html_text:
        return []
    # de-dup preservando orden
    seen, charts = set(), []
    for url in _IMG_SRC_RE.findall(html_text):
        if url not in seen:
            seen.add(url)
            charts.append(url)
    return charts


def _safe_float(val):
    try:
        if val is None:
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val):
    try:
        if val is None:
            return None
        return int(round(float(val)))
    except (TypeError, ValueError):
        return None


def _to_millions(market_cap):
    """Normaliza la capitalización a MILLONES de USD.

    Stocktwits suele devolver capitalización en USD crudos; si el valor es muy
    grande (>= 1e6) asumimos crudos y dividimos. Si ya viene en millones, se
    deja igual.
    """
    mc = _safe_float(market_cap)
    if mc is None:
        return None
    return mc / 1_000_000.0 if mc >= 1_000_000 else mc


def _sentiment_label(score: int | None) -> str:
    """>55 Bullish · <45 Bearish · 45-55 Neutral (ver PRD §9)."""
    if score is None:
        return "Neutral"
    if score > 55:
        return "Bullish"
    if score < 45:
        return "Bearish"
    return "Neutral"


def _volume_label(score: int | None) -> str:
    """>=66 High · >=33 Medium · resto Low."""
    if score is None:
        return "Low"
    if score >= 66:
        return "High"
    if score >= 33:
        return "Medium"
    return "Low"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


# ─────────────────────────────────────────────────────────────────────────────
# Derivación desde el stream por símbolo (RapidAPI no expone sentiment/summary
# agregados, así que se calculan a partir de los mensajes del propio stream).
# ─────────────────────────────────────────────────────────────────────────────
def _messages_from(raw) -> list:
    if isinstance(raw, dict):
        msgs = raw.get("messages")
        if isinstance(msgs, list):
            return [m for m in msgs if isinstance(m, dict)]
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, dict)]
    return []


def _parse_ts(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None


def _msgs_per_hour(messages: list) -> float:
    ts = [t for t in (_parse_ts(m.get("created_at")) for m in messages) if t]
    if len(ts) < 2:
        return float(len(messages))
    span_h = max((max(ts) - min(ts)).total_seconds() / 3600.0, 1 / 60)
    return len(ts) / span_h


def _declared_sentiments(messages: list):
    bull = bear = 0
    for m in messages:
        s = (m.get("entities") or {}).get("sentiment")
        basic = s.get("basic") if isinstance(s, dict) else None
        if basic == "Bullish":
            bull += 1
        elif basic == "Bearish":
            bear += 1
    return bull, bear


def _compute_sentiment_from_messages(messages: list):
    """(sentiment_score 1-100, message_volume_score 1-100) a partir del stream."""
    bull, bear = _declared_sentiments(messages)
    total = bull + bear
    sentiment_score = round(100 * bull / total) if total else 50
    volume_score = max(0, min(100, round(_msgs_per_hour(messages) * 8)))
    return sentiment_score, volume_score


def _derive_summary_from_messages(symbol: str, messages: list):
    """'Why trending' derivado: velocidad social + sesgo de sentimiento."""
    if not messages:
        return None
    bull, bear = _declared_sentiments(messages)
    declared = bull + bear
    score = round(100 * bull / declared) if declared else 50
    bias = "alcista" if score > 55 else "bajista" if score < 45 else "mixto"
    rate = round(_msgs_per_hour(messages))
    text = f"${symbol} acumula ~{rate} mensajes/hora en Stocktwits"
    if declared:
        text += (
            f", con sesgo {bias} ({round(100 * bull / declared)}% alcista / "
            f"{round(100 * bear / declared)}% bajista entre {declared} opiniones declaradas)"
        )
    return text + "."


# ─────────────────────────────────────────────────────────────────────────────
# Fetchers (mapean la respuesta cruda al contrato; sin caché ni DB)
# ─────────────────────────────────────────────────────────────────────────────
def _map_trending_symbol(raw: dict) -> dict | None:
    symbol = (raw.get("symbol") or "").upper()
    if not symbol:
        return None
    market_cap_m = _to_millions(raw.get("market_cap"))
    # Filtro de small caps: descartar caps desconocidas o >= $2,000M.
    if market_cap_m is None or market_cap_m >= SMALL_CAP_MAX_USD_MILLIONS:
        return None
    return {
        "symbol": symbol,
        "name": raw.get("title") or raw.get("name") or symbol,
        "market_cap": market_cap_m,
        "daily_volume": _safe_float(raw.get("volume") or raw.get("daily_volume")),
        "trending_score": _safe_float(raw.get("trending_score") or raw.get("score")),
        "sentiment_score": _safe_int(raw.get("sentiment_score")),
        "price": _safe_float(raw.get("price")),
        "change_pct": _safe_float(
            raw.get("change_percent")
            if raw.get("change_percent") is not None
            else raw.get("change_pct")
            if raw.get("change_pct") is not None
            else raw.get("change")
        ),
    }


def _map_trending_payload(raw) -> list:
    """Mapea la forma {symbols:[...]} de un endpoint de trending dedicado."""
    symbols = raw.get("symbols") if isinstance(raw, dict) else raw
    if not isinstance(symbols, list):
        return []
    out = [_map_trending_symbol(s) for s in symbols if isinstance(s, dict)]
    out = [o for o in out if o]
    out.sort(key=lambda r: (r["trending_score"] is None, -(r["trending_score"] or 0)))
    return out


def _radar_market_cap_millions(symbol: str):
    """Capitalización (en millones USD) best-effort vía Finviz (reusa scraper)."""
    try:
        from app.routers.ticker_analysis import scrape_finviz_snapshot
        return _to_millions((scrape_finviz_snapshot(symbol) or {}).get("market_cap"))
    except Exception as e:
        print(f"[STOCKTWITS] market cap lookup failed for {symbol}: {e}")
        return None


def _radar_row_from_stream(symbol: str, raw) -> dict | None:
    messages = _messages_from(raw)
    sym_obj = raw.get("symbol", {}) if isinstance(raw, dict) else {}
    name = sym_obj.get("title") or symbol

    price = None
    for m in messages:
        prices = m.get("prices") or []
        if prices:
            price = _safe_float(prices[0].get("price"))
            break

    sentiment_score, _ = _compute_sentiment_from_messages(messages)
    trending_score = round(min(100.0, _msgs_per_hour(messages) * 8), 1)
    market_cap_m = _radar_market_cap_millions(symbol)
    # Filtro small cap: descartar solo si la cap es CONOCIDA y >= $2,000M.
    if market_cap_m is not None and market_cap_m >= SMALL_CAP_MAX_USD_MILLIONS:
        return None

    return {
        "symbol": symbol,
        "name": name,
        "market_cap": market_cap_m,
        "daily_volume": None,
        "trending_score": trending_score,
        "sentiment_score": sentiment_score if messages else None,
        "price": price,
        "change_pct": None,
    }


def _build_radar_from_candidates() -> list:
    """Construye el Radar sondeando el universo configurado (RapidAPI)."""
    if not _has_credentials():
        return []
    from concurrent.futures import ThreadPoolExecutor

    tickers = RADAR_TICKERS[:RADAR_MAX_CANDIDATES]

    def _one(sym: str):
        try:
            raw = _http_get_json(
                PATH_STREAM.format(symbol=sym),
                params={"limit": STREAM_FETCH_LIMIT} if _is_rapidapi() else None,
                symbol=sym,
            )
        except Exception as e:
            print(f"[STOCKTWITS] radar probe failed for {sym}: {e}")
            return None
        return _radar_row_from_stream(sym, raw)

    rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(_one, tickers):
            if r:
                rows.append(r)
    rows.sort(key=lambda r: (r["trending_score"] is None, -(r["trending_score"] or 0)))
    return rows


def fetch_trending_small_caps() -> list:
    """Radar de Momentum: small caps en tendencia social. Resiliente → [] ante fallo."""
    # 1) Proveedor con endpoint de trending dedicado (API oficial).
    if PATH_TRENDING:
        try:
            mapped = _map_trending_payload(_http_get_json(PATH_TRENDING))
            if mapped:
                return mapped
        except Exception as e:
            print(f"[STOCKTWITS] trending fetch failed: {e}")
    # 2) RapidAPI / fallback: radar derivado del universo configurado.
    return _build_radar_from_candidates()


def _stream_params() -> dict | None:
    return {"limit": STREAM_FETCH_LIMIT} if _is_rapidapi() else None


def fetch_summary(symbol: str) -> dict:
    """Why It's Trending: catalizador (dedicado) o derivado del stream."""
    symbol = symbol.upper()
    raw = _http_get_json(PATH_SUMMARY.format(symbol=symbol), params=_stream_params(), symbol=symbol)
    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    summary = data.get("summary") or data.get("why_trending") or data.get("description")
    if not summary:
        summary = _derive_summary_from_messages(symbol, _messages_from(raw))
    return {
        "symbol": symbol,
        "why_trending": summary or None,
        "updated_at": data.get("updated_at") or _now_iso(),
    }


def _extract_sentiment_score(raw: dict):
    for key in ("sentiment_score", "sentiment", "score"):
        val = raw.get(key)
        if isinstance(val, dict):
            val = val.get("normalized") or val.get("value") or val.get("score")
            if isinstance(val, dict):
                val = val.get("value")
        if val is not None:
            return _safe_int(val)
    return None


def _extract_volume_score(raw: dict):
    for key in ("message_volume_score", "message_volume", "volume_score", "volume"):
        val = raw.get(key)
        if isinstance(val, dict):
            val = val.get("normalized") or val.get("value")
            if isinstance(val, dict):
                val = val.get("value")
        if val is not None:
            return _safe_int(val)
    return None


def fetch_sentiment(symbol: str) -> dict:
    """Sentiment Gauge: sentimiento + volumen (dedicado) o derivado del stream."""
    symbol = symbol.upper()
    raw = _http_get_json(PATH_SENTIMENT.format(symbol=symbol), params=_stream_params(), symbol=symbol)
    messages = _messages_from(raw)
    if messages:
        # RapidAPI: deriva de los mensajes del stream.
        sentiment_score, volume_score = _compute_sentiment_from_messages(messages)
    else:
        # API dedicada (o tests): lee los scores agregados.
        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        sentiment_score = _extract_sentiment_score(data)
        volume_score = _extract_volume_score(data)

    updated_at = (raw.get("data", raw) if isinstance(raw, dict) else {}).get("updated_at") or _now_iso()
    return {
        "symbol": symbol,
        "sentiment_score": sentiment_score if sentiment_score is not None else 50,
        "sentiment_label": _sentiment_label(sentiment_score),
        "message_volume_score": volume_score if volume_score is not None else 0,
        "message_volume_label": _volume_label(volume_score),
        "updated_at": updated_at,
    }


def _count_tickers(raw_msg: dict) -> int:
    syms = raw_msg.get("symbols")
    if isinstance(syms, list):
        return len(syms)
    # fallback: contar cashtags en el cuerpo
    body = raw_msg.get("body") or ""
    return len(re.findall(r"\$[A-Za-z]{1,6}", body))


def _map_user_sentiment(raw_msg: dict):
    entities = raw_msg.get("entities") or {}
    sentiment = entities.get("sentiment") if isinstance(entities, dict) else None
    if isinstance(sentiment, dict):
        basic = sentiment.get("basic")
        if basic in ("Bullish", "Bearish"):
            return basic
    return None


def fetch_stream(symbol: str, limit: int = DEFAULT_STREAM_LIMIT) -> list:
    """Zona de Debate Limpia: mensajes filtrados de spam/bots."""
    symbol = symbol.upper()
    limit = max(1, min(int(limit or DEFAULT_STREAM_LIMIT), MAX_STREAM_LIMIT))
    params = {"limit": max(limit, STREAM_FETCH_LIMIT)} if _is_rapidapi() else None
    raw = _http_get_json(PATH_STREAM.format(symbol=symbol), params=params, symbol=symbol)
    messages = _messages_from(raw)

    cleaned = []
    for m in messages:
        likes_raw = m.get("likes")
        likes_present = isinstance(likes_raw, dict)
        likes_count = (_safe_int(likes_raw.get("total")) or 0) if likes_present else 0
        is_trending = bool(m.get("trending_messages") or m.get("is_trending"))
        # Anti-spam: si la API expone likes, exige el mínimo (salvo trending).
        # RapidAPI no devuelve likes (null) → no se descarta por este criterio.
        if likes_present and likes_count < MIN_LIKES_THRESHOLD and not is_trending:
            continue
        # Descarta pump & dump (menciona demasiados tickers).
        if _count_tickers(m) > MAX_TICKERS_PER_MESSAGE:
            continue

        user = m.get("user") or {}
        cleaned.append({
            "message_id": _safe_int(m.get("id")),
            "body": _strip_html(m.get("body")),
            "created_at": m.get("created_at") or "",
            "username": user.get("username") or "anon",
            "avatar_url": user.get("avatar_url") or user.get("avatar_url_ssl") or "",
            "user_sentiment": _map_user_sentiment(m),
            "likes_count": likes_count,
        })

    cleaned.sort(key=lambda x: x["likes_count"], reverse=True)
    return cleaned[:limit]


def fetch_newsletter() -> list:
    """Newsletters & Chart Art: agregador RSS → JSON. Resiliente → [] ante fallo."""
    try:
        text = _http_get_text(PATH_NEWSLETTER)
    except Exception as e:  # feed global: nunca propaga
        print(f"[STOCKTWITS] newsletter fetch failed: {e}")
        return []

    import feedparser
    feed = feedparser.parse(text)
    items = []
    for entry in getattr(feed, "entries", []) or []:
        content_html = entry.get("summary") or entry.get("description") or ""
        # feedparser expone content[].value para feeds con <content:encoded>
        if not content_html and entry.get("content"):
            try:
                content_html = entry["content"][0].get("value", "")
            except (IndexError, AttributeError):
                content_html = ""
        items.append({
            "title": entry.get("title") or "",
            "published_at": entry.get("published") or entry.get("updated") or _now_iso(),
            "author": entry.get("author") or "Stocktwits Editorial",
            "content_html": content_html,
            "charts": _extract_charts(content_html),
            "link": entry.get("link") or "",
        })
    return items


# ─────────────────────────────────────────────────────────────────────────────
# Caché Stale-While-Revalidate sobre users.duckdb (tabla ticker_analysis_cache)
# ─────────────────────────────────────────────────────────────────────────────
_swr_inflight: set = set()
_swr_inflight_lock = threading.Lock()


def _cache_read(cache_key: str, endpoint: str):
    from app.database import get_user_db_connection, get_user_db_lock
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            return con.execute(
                "SELECT payload, updated_at FROM ticker_analysis_cache "
                "WHERE ticker = ? AND endpoint = ?",
                [cache_key, endpoint],
            ).fetchone()
        finally:
            con.close()


def _cache_store(cache_key: str, endpoint: str, payload):
    from app.database import get_user_db_connection, get_user_db_lock
    try:
        with get_user_db_lock():
            con = get_user_db_connection()
            try:
                con.execute(
                    "INSERT OR REPLACE INTO ticker_analysis_cache "
                    "(ticker, endpoint, payload, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    [cache_key, endpoint, json.dumps(payload)],
                )
            finally:
                con.close()
        from app.gcs_sync import mark_user_db_dirty
        mark_user_db_dirty()
    except Exception as e:
        print(f"[STOCKTWITS][SWR] store failed for {cache_key}/{endpoint}: {e}")


def _swr_cache(cache_key: str, endpoint: str, ttl: timedelta, fetch_fn, default):
    """Stale-while-revalidate genérico (payload puede ser list o dict).

    - Si hay copia cacheada se devuelve YA (aunque esté obsoleta) y se refresca
      en un hilo daemon.
    - Si no hay copia previa se busca síncronamente; los errores tipados de
      Stocktwits se propagan (el router los mapea a 404/429/503), cualquier otro
      fallo devuelve `default` (resiliencia).
    """
    row = None
    try:
        row = _cache_read(cache_key, endpoint)
    except Exception as e:
        print(f"[STOCKTWITS][SWR] read failed for {cache_key}/{endpoint}: {e}")

    if row is not None:
        payload, updated_at = row
        parsed = json.loads(payload) if isinstance(payload, str) else payload
        stale = True
        try:
            stale = (datetime.now() - updated_at) > ttl
        except Exception:
            pass
        if stale:
            key = (cache_key, endpoint)
            with _swr_inflight_lock:
                already = key in _swr_inflight
                if not already:
                    _swr_inflight.add(key)
            if not already:
                def _refresh():
                    try:
                        _cache_store(cache_key, endpoint, fetch_fn())
                        print(f"[STOCKTWITS][SWR] refreshed {cache_key}/{endpoint}")
                    except Exception as e:
                        print(f"[STOCKTWITS][SWR] refresh failed for {cache_key}/{endpoint}: {e}")
                    finally:
                        with _swr_inflight_lock:
                            _swr_inflight.discard(key)
                threading.Thread(target=_refresh, daemon=True).start()
        return parsed

    # Nunca visto: fetch síncrono.
    try:
        payload = fetch_fn()
    except StocktwitsError:
        raise  # el router lo mapea a 404/429/503
    except Exception as e:
        print(f"[STOCKTWITS][SWR] first fetch failed for {cache_key}/{endpoint}: {e}")
        return default

    _cache_store(cache_key, endpoint, payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# API pública cacheada (consumida por el router social)
# ─────────────────────────────────────────────────────────────────────────────
def get_trending() -> list:
    return _swr_cache(KEY_TRENDING, ENDPOINT_TRENDING, TTL_TRENDING,
                      fetch_trending_small_caps, default=[])


def get_summary(symbol: str) -> dict:
    symbol = symbol.upper()
    return _swr_cache(symbol, ENDPOINT_SUMMARY, TTL_SUMMARY,
                      lambda: fetch_summary(symbol),
                      default={"symbol": symbol, "why_trending": None, "updated_at": _now_iso()})


def get_sentiment(symbol: str) -> dict:
    symbol = symbol.upper()
    return _swr_cache(symbol, ENDPOINT_SENTIMENT, TTL_SENTIMENT,
                      lambda: fetch_sentiment(symbol),
                      default={
                          "symbol": symbol, "sentiment_score": 50, "sentiment_label": "Neutral",
                          "message_volume_score": 0, "message_volume_label": "Low",
                          "updated_at": _now_iso(),
                      })


def get_stream(symbol: str, limit: int = DEFAULT_STREAM_LIMIT) -> list:
    symbol = symbol.upper()
    # El límite forma parte de la clave de endpoint para no mezclar tamaños.
    endpoint = f"{ENDPOINT_STREAM}_{max(1, min(int(limit or DEFAULT_STREAM_LIMIT), MAX_STREAM_LIMIT))}"
    return _swr_cache(symbol, endpoint, TTL_STREAM,
                      lambda: fetch_stream(symbol, limit), default=[])


def get_newsletter() -> list:
    return _swr_cache(KEY_NEWSLETTER, ENDPOINT_NEWSLETTER, TTL_NEWSLETTER,
                      fetch_newsletter, default=[])
