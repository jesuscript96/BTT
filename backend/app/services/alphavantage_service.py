"""Cliente para Alpha Vantage — enriquecimiento DETERMINISTA del perfil.

Sustituye a yfinance como fuente primaria de los campos que Massive/SEC no dan y
que antes salían de Yahoo (flaky, y peor desde IP de datacenter): float de
acciones, % en manos de insiders/instituciones y EBITDA. Un solo endpoint
(`OVERVIEW`) los trae todos con una key, cobertura verificada en small-caps
activas (ARBE, KOSS, GNS) frescas al último trimestre.

Tier gratis = 25 requests/día. Por eso se usa SOLO como enriquecimiento NO
bloqueante y cacheado 24h (1 llamada por ticker y día): si se agota la cuota, el
que llama cae a yfinance o deja el campo vacío, sin romper la página. Subir a
premium es cambiar la cuota, no el código.

Semántica: dict normalizado en éxito; None si no hay cobertura (p.ej. deslistada,
respuesta {}) o si se agotó el rate limit (Alpha Vantage lo señala con las claves
"Note"/"Information"). El llamador trata None como "sin dato" → fallback.
"""

import os
import threading
import time

import requests

API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")
BASE_URL = "https://www.alphavantage.co/query"
DEFAULT_TIMEOUT = 8

_session = None
_session_lock = threading.Lock()


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                s = requests.Session()
                s.headers.update({"User-Agent": "Edgecute/1.0"})
                _session = s
    return _session


def _to_float(v):
    """AV entrega números como strings; 'None'/'-'/'' → None."""
    if v in (None, "", "-", "None", "n/a", "NA"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get_overview(ticker: str) -> dict | None:
    """`OVERVIEW` normalizado para el enriquecimiento del perfil.

    Devuelve solo los campos que aportan valor sobre Massive/SEC, en el MISMO
    formato que consume el payload de /{ticker} (fracciones, no porcentajes):
      float_shares, shares_outstanding, held_percent_insiders,
      held_percent_institutions, ebitda, sector, industry, country.
    None si no hay cobertura o se agotó la cuota diaria.
    """
    ticker = (ticker or "").upper().strip()
    if not ticker or not API_KEY:
        return None
    try:
        resp = _get_session().get(
            BASE_URL,
            params={"function": "OVERVIEW", "symbol": ticker, "apikey": API_KEY},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[AV] overview transport error for {ticker}: {e}")
        return None

    # Rate limit / mensajes informativos → tratar como "sin dato" (transitorio).
    if not isinstance(data, dict) or "Note" in data or "Information" in data:
        if isinstance(data, dict) and (data.get("Note") or data.get("Information")):
            print(f"[AV] rate limit/nota para {ticker} (cuota diaria agotada probablemente)")
        return None
    # Sin cobertura (deslistada / símbolo desconocido) → {} o sin Symbol.
    if not data.get("Symbol"):
        return None

    # PercentInsiders/Institutions vienen como '5.494' (porcentaje). El payload de
    # la app guarda FRACCIONES (el frontend multiplica ×100), igual que yfinance.
    ins = _to_float(data.get("PercentInsiders"))
    inst = _to_float(data.get("PercentInstitutions"))

    out = {
        "float_shares": _to_float(data.get("SharesFloat")),
        "shares_outstanding": _to_float(data.get("SharesOutstanding")),
        "held_percent_insiders": (ins / 100.0) if ins is not None else None,
        "held_percent_institutions": (inst / 100.0) if inst is not None else None,
        "ebitda": _to_float(data.get("EBITDA")),
        "sector": (data.get("Sector") or None),
        "industry": (data.get("Industry") or None),
        "country": (data.get("Country") or None),
    }
    # Si no vino ni float ni % ownership, no aporta nada sobre Massive → None.
    if not any(out[k] is not None for k in
               ("float_shares", "held_percent_insiders", "held_percent_institutions", "ebitda")):
        return None
    return out
