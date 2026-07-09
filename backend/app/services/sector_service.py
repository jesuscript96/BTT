"""
Sector de la empresa para Market Analysis (PRD docs/market-analysis/PRD_GAPS_BY_SECTOR.md).

El lake NO tiene sector (massive.tickers = ticker/name/market/primary_exchange/type/active).
Se deriva del código SIC:
  · fuente primaria: Massive get_overview().sic_code  (~63% del universo filtrado)
  · fallback:        SEC EDGAR (company_tickers.json → CIK → submissions/CIK.json.sic)
                     recupera ~7/8 de los que Massive no cubre → cobertura combinada ~90-95%.

sic_to_sector() es PURA (unit-testable sin red); resolve_sector() hace las llamadas.
La orquestación real (enriquecer el universo → parquet) vive en scripts/build_ticker_sector.py;
en request-time NUNCA se llama a la API: se lee la tabla de referencia (cache_service).
"""
from __future__ import annotations

from typing import Optional

# 11 sectores estilo Yahoo/Finviz + buckets de residuo
SECTORS = (
    "Healthcare", "Technology", "Financial Services", "Consumer Cyclical",
    "Consumer Defensive", "Communication Services", "Industrials",
    "Basic Materials", "Energy", "Real Estate", "Utilities",
)
OTHER = "Other"          # tiene SIC pero no mapea
NO_SECTOR = "Sin sector"  # sin SIC en ninguna fuente


def sic_to_sector(sic) -> str:
    """
    SIC de 4 dígitos → sector Yahoo/Finviz. Reglas ORDENADAS: los rangos
    específicos (drugs, semis, REITs, SPACs) van ANTES que su rango general.
    Casos frontera verificados en el probe 08-jul-2026 (8731 biotech→Healthcare,
    3721 aircraft→Industrials, 8742 consulting→Industrials, 7372 software→Tech).
    Devuelve OTHER si no mapea; el llamador decide NO_SECTOR cuando no hay SIC.
    """
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return NO_SECTOR

    # ── Healthcare (específicos primero: farma dentro de químicos, instrumentos médicos) ──
    if 2833 <= s <= 2836:            # medicinal chemicals & pharma preparations
        return "Healthcare"
    if s == 3826 or 3841 <= s <= 3851:  # lab/medical instruments
        return "Healthcare"
    if 8000 <= s <= 8099:            # health services
        return "Healthcare"
    if s in (8731, 8734):            # commercial physical & biological research (biotech), testing labs
        return "Healthcare"

    # ── Technology (hardware/semis/software, antes de maquinaria/servicios generales) ──
    if 3570 <= s <= 3579:            # computer & office equipment
        return "Technology"
    if 3660 <= s <= 3699:            # comms equipment, semiconductors, electronic components
        return "Technology"
    if 7370 <= s <= 7379:            # computer programming, data processing, software
        return "Technology"
    if 3812 <= s <= 3825 or s == 3674:  # search/nav instruments, semiconductors
        return "Technology"

    # ── Energy ──
    if 1200 <= s <= 1399:            # coal, oil & gas extraction
        return "Energy"
    if 2900 <= s <= 2999:            # petroleum refining
        return "Energy"
    if s == 4610 or s == 4922 or s == 4924:  # pipelines / gas transmission-distribution (borderline)
        return "Energy"

    # ── Real Estate ──
    if 6500 <= s <= 6599:            # real estate, REITs
        return "Real Estate"

    # ── Financial Services (incluye 6770 blank checks / SPACs, MUY común en small-caps) ──
    if 6000 <= s <= 6499 or 6700 <= s <= 6799:
        return "Financial Services"

    # ── Utilities ──
    if 4900 <= s <= 4999:
        return "Utilities"

    # ── Communication Services (telecom, publishing, media, motion pictures) ──
    if 4800 <= s <= 4899 or 2700 <= s <= 2799 or 7800 <= s <= 7841:
        return "Communication Services"

    # ── Consumer Defensive (food, beverage, tobacco, food retail, drug stores, education) ──
    if 100 <= s <= 999 or 2000 <= s <= 2199 or 5400 <= s <= 5499 or s == 5912 or 8200 <= s <= 8299:
        return "Consumer Defensive"

    # ── Consumer Cyclical (apparel, autos, retail, restaurants, hotels, recreation) ──
    if 2300 <= s <= 2399 or 3140 <= s <= 3149 or 3630 <= s <= 3659:
        return "Consumer Cyclical"
    if 3700 <= s <= 3716 or 3751 <= s <= 3799:   # motor vehicles, motorcycles/bikes
        return "Consumer Cyclical"
    if 5200 <= s <= 5999:            # retail (los específicos defensivos ya salieron arriba)
        return "Consumer Cyclical"
    if 5000 <= s <= 5199:            # wholesale durable/nondurable → cíclico
        return "Consumer Cyclical"
    if s in (7000, 7011) or 7200 <= s <= 7299 or 7900 <= s <= 7999 or 7400 <= s <= 7699:
        return "Consumer Cyclical"

    # ── Basic Materials (mining, metals, chemicals no-farma, paper, wood) ──
    if 1000 <= s <= 1099 or 1400 <= s <= 1499:   # metal / nonmetallic mining
        return "Basic Materials"
    if 2800 <= s <= 2824 or 2840 <= s <= 2899:   # industrial/agri chemicals, paints
        return "Basic Materials"
    if 2400 <= s <= 2499 or 2600 <= s <= 2699:   # lumber, paper
        return "Basic Materials"
    if 3300 <= s <= 3399:            # primary metal
        return "Basic Materials"

    # ── Industrials (construcción, maquinaria, transporte, aeroespacial, servicios B2B) ──
    if 1500 <= s <= 1799:            # construction
        return "Industrials"
    if 3400 <= s <= 3569 or 3580 <= s <= 3629:   # fabricated metal, industrial machinery, electrical equip
        return "Industrials"
    if 3720 <= s <= 3749:            # aircraft, aerospace, ships, rail equipment
        return "Industrials"
    if 4000 <= s <= 4799:            # transportation (rail, trucking, air, water)
        return "Industrials"
    if 8711 <= s <= 8748:            # engineering, accounting, management consulting (8742)
        return "Industrials"
    if 3440 <= s <= 3599 or 3800 <= s <= 3999:   # otros manufacturing/instruments
        return "Industrials"

    return OTHER


def resolve_sector(ticker: str) -> dict:
    """
    {ticker, sic_code, sic_description, sector, source} para UN ticker.
    Massive primero; si no hay sic_code, SEC EDGAR. source ∈ massive|sec|none.
    Pensado para el script de build (hace red); no se usa en request-time.
    """
    ticker = (ticker or "").upper().strip()
    out = {"ticker": ticker, "sic_code": None, "sic_description": None,
           "sector": NO_SECTOR, "source": "none"}
    if not ticker:
        return out

    # 1) Massive
    try:
        from app.services import massive_service
        ov = massive_service.get_overview(ticker) or {}
        sic = ov.get("sic_code")
        if sic:
            out.update(sic_code=str(sic), sic_description=ov.get("sic_description"),
                       sector=sic_to_sector(sic), source="massive")
            return out
    except Exception:
        pass

    # 2) SEC EDGAR (submissions.sic)
    try:
        sic, desc = _sec_sic(ticker)
        if sic:
            out.update(sic_code=str(sic), sic_description=desc,
                       sector=sic_to_sector(sic), source="sec")
    except Exception:
        pass
    return out


# ── SEC EDGAR helpers (ticker → CIK → submissions.sic) ───────────────────────
_sec_cik_map: Optional[dict] = None


def _sec_headers() -> dict:
    import os
    ua = os.getenv("SEC_USER_AGENT", "Edgecute research contact@edgecute.com")
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def _load_sec_cik_map() -> dict:
    """ticker(upper) → CIK 10 dígitos desde company_tickers.json (cacheado en proceso)."""
    global _sec_cik_map
    if _sec_cik_map is not None:
        return _sec_cik_map
    import requests
    m: dict = {}
    try:
        data = requests.get("https://www.sec.gov/files/company_tickers.json",
                            headers=_sec_headers(), timeout=20).json()
        for v in data.values():
            t = str(v.get("ticker", "")).upper()
            if t:
                m[t] = str(v.get("cik_str")).zfill(10)
    except Exception:
        pass
    _sec_cik_map = m
    return m


def _sec_sic(ticker: str):
    """(sic, sic_description) desde SEC submissions, o (None, None)."""
    import requests
    cik = _load_sec_cik_map().get(ticker.upper())
    if not cik:
        # fallback: CIK vía Massive (cubre algún deslistado que sí tiene overview parcial)
        try:
            from app.services import massive_service
            cik = massive_service.get_cik(ticker)
        except Exception:
            cik = None
    if not cik:
        return None, None
    try:
        sub = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                           headers=_sec_headers(), timeout=20).json()
        sic = sub.get("sic")
        return (str(sic) if sic else None), sub.get("sicDescription")
    except Exception:
        return None, None
