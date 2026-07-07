"""EDGAR document ingestion + extraction motor for Edgie.

Generaliza el patrón "ir al documento real" (no solo metadatos): resuelve el CIK,
lista filings (data.sec.gov/submissions), baja el documento primario, lo pasa a
texto limpio y recorta la sección relevante para alimentar a Edgie sin volcar el
documento entero (un 20-F no cabe en contexto).

Reutilizable de dos formas:
  - Pre-extracción determinista (informe / KB del chat).
  - Tools del chat agentic (las mismas funciones expuestas como herramientas).

Tolerante a fallos: ante red caída / formato inesperado devuelve None/[] sin
romper el flujo que lo invoca.
"""

import logging
import re
import threading
import time

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger("edgar")

# SEC exige un User-Agent identificable con contacto.
SEC_HEADERS = {"User-Agent": "Edgecute/1.0 (support@edgecute.com)"}

# ── Caché en proceso (los filings no cambian; los docs son grandes) ──────────
_CIK_MAP = None
_CIK_MAP_LOCK = threading.Lock()
_DOC_CACHE: dict = {}            # accession+doc -> (text, expiry)
_DOC_CACHE_LOCK = threading.Lock()
_DOC_TTL = 6 * 3600             # 6h: un filing publicado no cambia
_SUBMISSIONS_CACHE: dict = {}    # cik -> (json, expiry)
_SUBMISSIONS_LOCK = threading.Lock()
_SUBMISSIONS_TTL = 30 * 60      # 30 min: /sec-filings, /insiders y tools de Edgie la comparten
_XBRL_CACHE: dict = {}           # cik+concept -> (history, expiry)
_XBRL_LOCK = threading.Lock()
_XBRL_TTL = 6 * 3600


def resolve_cik(ticker: str):
    """ticker -> CIK de 10 dígitos (con ceros a la izquierda). None si no existe."""
    global _CIK_MAP
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return None
    with _CIK_MAP_LOCK:
        if _CIK_MAP is None:
            try:
                r = requests.get(
                    "https://www.sec.gov/files/company_tickers.json",
                    headers=SEC_HEADERS, timeout=10,
                )
                data = r.json()
                _CIK_MAP = {
                    str(row["ticker"]).upper(): str(row["cik_str"]).zfill(10)
                    for row in data.values()
                }
            except Exception as e:
                logger.warning("[EDGAR] no se pudo cargar company_tickers.json: %s", e)
                _CIK_MAP = {}
    return _CIK_MAP.get(ticker)


def _get_submissions_recent(cik: str) -> dict:
    """JSON `filings.recent` de data.sec.gov/submissions, cacheado 30 min.

    Lo comparten /sec-filings, /insiders y las tools de Edgie: una sola request
    por CIK y ventana en vez de una por endpoint.
    """
    if not cik:
        return {}
    now = time.time()
    with _SUBMISSIONS_LOCK:
        hit = _SUBMISSIONS_CACHE.get(cik)
        if hit and hit[1] > now:
            return hit[0]
    try:
        r = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=SEC_HEADERS, timeout=12,
        )
        recent = r.json().get("filings", {}).get("recent", {})
    except Exception as e:
        logger.warning("[EDGAR] submissions falló para CIK %s: %s", cik, e)
        return {}
    with _SUBMISSIONS_LOCK:
        _SUBMISSIONS_CACHE[cik] = (recent, now + _SUBMISSIONS_TTL)
    return recent


def _rows_from_recent(recent: dict, limit: int, keep) -> list:
    """Convierte el formato columnar de submissions en filas filtradas por keep(form)."""
    forms_list = recent.get("form", [])
    accns = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    dates = recent.get("filingDate", [])
    descs = recent.get("primaryDocDescription", [])

    out = []
    for i in range(len(forms_list)):
        f = forms_list[i]
        if not keep(f):
            continue
        out.append({
            "form": f,
            "accession": accns[i] if i < len(accns) else None,
            "primary_document": docs[i] if i < len(docs) else None,
            "date": dates[i] if i < len(dates) else None,
            "description": descs[i] if i < len(descs) else "",
        })
        if len(out) >= limit:
            break
    return out


def list_filings(cik: str, forms=None, limit: int = 40) -> list:
    """Filings recientes desde data.sec.gov/submissions.

    forms: lista de prefijos a filtrar (p.ej. ["20-F","10-K"]). None = todos.
    Devuelve [{form, accession, primary_document, date, description}].
    """
    recent = _get_submissions_recent(cik)
    forms_up = [f.upper() for f in (forms or [])]
    keep = (lambda f: True) if not forms_up else (
        lambda f: any(f.upper().startswith(x) for x in forms_up)
    )
    return _rows_from_recent(recent, limit, keep)


# Formularios de ownership Section 16. Match EXACTO (no por prefijo: "4"
# como prefijo también casaría "424B5").
_OWNERSHIP_FORMS = {"3", "4", "5", "3/A", "4/A", "5/A"}


def list_ownership_filings(cik: str, limit: int = 12) -> list:
    """Forms 3/4/5 (transacciones de insiders) del emisor, más recientes primero."""
    recent = _get_submissions_recent(cik)
    return _rows_from_recent(recent, limit, lambda f: f.upper() in _OWNERSHIP_FORMS)


# Conceptos XBRL de posición de caja, en orden de preferencia. Massive no expone
# `cash` en balance_sheet (solo flujos), así que el cash para runway sale de la
# fuente primaria: la API XBRL oficial de SEC.
CASH_CONCEPTS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "CashCashEquivalentsAndShortTermInvestments",
    "Cash",
)


def get_xbrl_concept_history(cik: str, concepts=CASH_CONCEPTS, limit: int = 24) -> list:
    """Serie histórica [{date, value, form}] de un concepto us-gaap vía
    data.sec.gov/api/xbrl/companyconcept. Prueba `concepts` en orden y devuelve
    la primera con datos. Dedupe por fecha fin (gana el filing más reciente).
    Cache 6h en proceso. [] si el emisor no reporta ninguno (p. ej. sin XBRL).
    """
    if not cik:
        return []
    now = time.time()
    key = f"{cik}:{concepts[0] if concepts else ''}"
    with _XBRL_LOCK:
        hit = _XBRL_CACHE.get(key)
        if hit and hit[1] > now:
            return hit[0]

    history: list = []
    for concept in concepts:
        try:
            r = requests.get(
                f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json",
                headers=SEC_HEADERS, timeout=10,
            )
            if r.status_code != 200:
                continue
            facts = (r.json().get("units") or {}).get("USD") or []
        except Exception as e:
            logger.warning("[EDGAR] companyconcept %s falló para CIK %s: %s", concept, cik, e)
            continue
        by_end: dict = {}
        for f in facts:
            end = f.get("end")
            if not end or f.get("val") is None:
                continue
            prev = by_end.get(end)
            if prev is None or (f.get("filed") or "") >= (prev.get("filed") or ""):
                by_end[end] = f
        if by_end:
            rows = sorted(by_end.values(), key=lambda f: f["end"])[-limit:]
            history = [
                {"date": f["end"], "value": float(f["val"]), "form": f.get("form")}
                for f in rows
            ]
            break

    with _XBRL_LOCK:
        _XBRL_CACHE[key] = (history, now + _XBRL_TTL)
    return history


def _doc_url(cik: str, accession: str, primary_document: str) -> str:
    accn_nodash = (accession or "").replace("-", "")
    cik_int = str(int(cik))  # la ruta Archives usa el CIK sin ceros a la izquierda
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_nodash}/{primary_document}"


def fetch_ownership_xml(cik: str, accession: str, primary_document: str):
    """XML crudo de un filing de ownership (Form 3/4/5).

    Camino rápido: el primaryDocument de submissions suele ser
    "xslF345X05/wk-form4_x.xml" (versión renderizada); el XML crudo es el
    basename sin el prefijo xsl. Si no, fallback a descubrirlo por index.json.
    Una sola request en el caso común vs las dos del camino legacy.
    """
    if not (cik and accession):
        return None
    base_doc = (primary_document or "").split("/")[-1]
    if base_doc.lower().endswith(".xml"):
        try:
            r = requests.get(_doc_url(cik, accession, base_doc), headers=SEC_HEADERS, timeout=8)
            if r.status_code == 200 and "<" in r.text[:100]:
                return r.text
        except Exception as e:
            logger.warning("[EDGAR] xml directo falló %s/%s: %s", accession, base_doc, e)
    # Fallback: localizar el .xml en el índice del filing
    try:
        folder = _doc_url(cik, accession, "").rstrip("/")
        idx = requests.get(f"{folder}/index.json", headers=SEC_HEADERS, timeout=8)
        items = idx.json().get("directory", {}).get("item", [])
        xml_name = None
        for it in items:
            low = it.get("name", "").lower()
            if low.endswith(".xml") and "index" not in low and not low.startswith("r"):
                xml_name = it.get("name")
                if any(k in low for k in ("form3", "form4", "form5", "ownership", "wf-form", "wk-form", "primary_doc")):
                    break
        if not xml_name:
            return None
        return requests.get(f"{folder}/{xml_name}", headers=SEC_HEADERS, timeout=8).text
    except Exception as e:
        logger.warning("[EDGAR] no se pudo descargar XML de %s: %s", accession, e)
        return None


def html_to_text(html: str) -> str:
    """HTML/iXBRL -> texto plano legible. Mantiene tablas (los directivos suelen
    ir en tablas), elimina script/style y colapsa espacios."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def fetch_document_text(cik: str, accession: str, primary_document: str,
                        max_chars: int = 800_000):
    """Baja y limpia el documento primario. Cacheado en proceso por accession+doc."""
    if not (cik and accession and primary_document):
        return None
    key = f"{accession}/{primary_document}"
    now = time.time()
    with _DOC_CACHE_LOCK:
        hit = _DOC_CACHE.get(key)
        if hit and hit[1] > now:
            return hit[0]
    try:
        url = _doc_url(cik, accession, primary_document)
        r = requests.get(url, headers=SEC_HEADERS, timeout=20)
        text = html_to_text(r.text)[:max_chars]
    except Exception as e:
        logger.warning("[EDGAR] fetch doc falló %s: %s", key, e)
        return None
    with _DOC_CACHE_LOCK:
        _DOC_CACHE[key] = (text, now + _DOC_TTL)
    return text


def extract_section(text: str, keys, end_keys=None, max_chars: int = 24_000,
                    min_len: int = 400):
    """Recorta la sección que empieza por alguna de `keys`.

    El índice (TOC) también contiene los títulos, así que en vez de la primera
    ocurrencia elegimos la que produce la **sección más larga**: el TOC es corto
    (el siguiente título aparece enseguida) y el cuerpo real es largo. Corta en el
    primer `end_keys` posterior o a `max_chars`. None si no encuentra nada útil.
    """
    if not text:
        return None
    low = text.lower()
    n = len(text)

    positions = []
    for k in keys:
        kl = k.lower()
        start = 0
        while True:
            i = low.find(kl, start)
            if i == -1:
                break
            positions.append(i)
            start = i + len(kl)
    if not positions:
        return None

    best = None
    best_len = -1
    for start in positions:
        end = min(n, start + max_chars)
        if end_keys:
            for k in end_keys:
                j = low.find(k.lower(), start + 80)
                if j != -1:
                    end = min(end, j)
        seg_len = end - start
        if seg_len > best_len:
            best_len = seg_len
            best = (start, end)
    if not best:
        return None
    seg = text[best[0]:best[1]].strip()
    return seg if len(seg) >= min_len else None


def extract_item(text: str, item_no: int, max_chars: int = 60_000,
                 min_len: int = 400):
    """Para filings con estructura 'ITEM N' (20-F, 10-K, 10-Q): recorta de
    'ITEM <n>' al siguiente 'ITEM <n+1>'. Elige el span más largo: el cuerpo real
    es largo; el TOC y las referencias cruzadas dan spans cortos. None si no hay.
    """
    if not text:
        return None
    low = text.lower()
    starts = [m.start() for m in re.finditer(rf"item\s*{item_no}\b", low)]
    nexts = [m.start() for m in re.finditer(rf"item\s*{item_no + 1}\b", low)]
    if not starts:
        return None
    best = None
    best_len = -1
    for s in starts:
        after = [e for e in nexts if e > s + 50]
        end = min(after) if after else min(len(text), s + max_chars)
        end = min(end, s + max_chars)
        if end - s > best_len:
            best_len = end - s
            best = (s, end)
    if not best:
        return None
    seg = text[best[0]:best[1]].strip()
    return seg if len(seg) >= min_len else None


def read_relevant(text: str, query: str, chunk: int = 9_000,
                  max_chars: int = 18_000):
    """Devuelve la región del documento con mayor densidad de términos de `query`.

    Buscador genérico (sin catálogo por tipo de doc): trocea el texto en ventanas
    solapadas y devuelve la de mayor puntuación. Para cuando el modelo pide algo
    libre ('plan of distribution', 'warrant exercise price', 'board of directors').
    """
    if not text:
        return None
    terms = list({t for t in re.findall(r"[a-zA-Z]{4,}", (query or "").lower())})
    if not terms:
        return text[:max_chars]
    low = text.lower()
    n = len(text)
    step = max(1, chunk // 2)
    best_i = 0
    best_score = -1
    for i in range(0, max(1, n), step):
        c = low[i:i + chunk]
        score = sum(c.count(t) for t in terms)
        if score > best_score:
            best_score = score
            best_i = i
    start = max(0, best_i - 1_000)
    return text[start:start + max_chars]


def get_filing_item(ticker: str, forms, item_no: int, max_chars: int = 60_000):
    """ticker -> filing más reciente de `forms` -> ITEM `item_no` recortado."""
    cik = resolve_cik(ticker)
    if not cik:
        return None
    filings = list_filings(cik, forms=forms, limit=5)
    if not filings:
        return None
    f = filings[0]
    text = fetch_document_text(cik, f["accession"], f["primary_document"])
    if not text:
        return None
    seg = extract_item(text, item_no, max_chars=max_chars)
    return {
        "ticker": ticker.upper(), "form": f["form"], "date": f["date"],
        "url": _doc_url(cik, f["accession"], f["primary_document"]),
        "section": seg, "section_found": seg is not None,
    }


def get_document_section(ticker: str, forms, section_keys, end_keys=None,
                         max_chars: int = 24_000):
    """Cadena completa: ticker -> CIK -> filing más reciente del tipo `forms` ->
    documento -> sección recortada. Devuelve dict con metadatos + texto, o None.
    """
    cik = resolve_cik(ticker)
    if not cik:
        return None
    filings = list_filings(cik, forms=forms, limit=5)
    if not filings:
        return None
    f = filings[0]
    text = fetch_document_text(cik, f["accession"], f["primary_document"])
    if not text:
        return None
    section = extract_section(text, section_keys, end_keys=end_keys, max_chars=max_chars)
    return {
        "ticker": ticker.upper(),
        "form": f["form"],
        "date": f["date"],
        "url": _doc_url(cik, f["accession"], f["primary_document"]),
        "section": section,
        "section_found": section is not None,
    }
