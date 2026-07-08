"""
Market Analysis service — agregación en Python puro sobre los gappers ya filtrados.

Implementa los módulos del MVP (docs/market-analysis/PRD.md) con el Patch v2.1
(docs/market-analysis/PRD_PATCH_v2.1.md) aplicado:
  · MA-01 KPIs (5 tarjetas, sub-valores PM/RTH)   · MA-02 Time Distribution (HOD/LOD/PMH)
  · Ventanas de Fade (sustituye a MAE/MFE)        · Filtros de calidad de universo (§01)

Diseño (anclado en GUIA_PRD_EJECUTABLE §6.1 "routers finos, services gordos"):
  El filtrado/selección pesado se queda en query_service.build_screener_query (SQL sobre
  daily_metrics). Este módulo recibe los dicts de fila resultantes y calcula la estadística
  descriptiva en Python, para que la matemática sea unit-testable SIN BD viva
  (los ejemplos numéricos de los PRDs §5 se vuelven asserts en test_market_analysis.py).

Filtros de calidad (Patch v2.1 §01) — punto ÚNICO en apply_quality_filters, aplicado a
periodo actual, periodo anterior (deltas) y a las curvas MA-04 (en su builder):
  · reverse split ≤5 días naturales   · gap_pct > 1000%   · black swan 5min > 300%
  · paridad hot/cold: tipos CS/ADRC/OS y splits del mismo día también en el hot path.

Derivado ma_daily (cold_storage/derived/ma_daily/*.parquet, scripts/backfill_ma_derived.py):
  m0_return_pct (close vela 09:30), m90_return_pct (close ≤11:00), max_spike_5m_pct.
  Se inyecta por (ticker, fecha) vía merge_derived; si falta, black swan no evalúa
  (fail-open) y las franjas 09:30/11:00 emiten pending_backfill.

Notas de alcance:
  · close_lt_vwap_pct → None (pospuesto a v1.2 producto: depende de day_vwap).
  · País/Sector/Float/Hot Sectors → Fase 2 (no se calculan aquí).

Nomenclatura: las claves de fila son las columnas literales de daily_metrics
(ver processor_service.process_daily_metrics): gap_pct, pm_high, pm_low, pm_high_time,
hod_time, lod_time, rth_open, rth_high, rth_low, rth_volume, pm_volume, close_1559,
day_return_pct, prev_close, timestamp, ticker, m30_return_pct, m60_return_pct, pmh_gap_pct.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# ── helpers ──────────────────────────────────────────────────────────────────

def safe_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return 0.0
        return fv
    except (TypeError, ValueError):
        return 0.0


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _quantile(xs_sorted: List[float], q: float) -> float:
    """Percentil con interpolación lineal — equivalente a DuckDB QUANTILE_CONT."""
    n = len(xs_sorted)
    if n == 0:
        return 0.0
    if n == 1:
        return xs_sorted[0]
    pos = q * (n - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs_sorted[int(pos)]
    frac = pos - lo
    return xs_sorted[lo] + (xs_sorted[hi] - xs_sorted[lo]) * frac


def _to_minutes(time_str: Any) -> Optional[int]:
    """
    Minutos desde medianoche a partir del campo de hora. Acepta:
      · 'HH:MM' (lo que produce el processor)
      · 'YYYY-MM-DD HH:MM[:SS]' / ISO 'YYYY-MM-DDTHH:MM' (lo que hay en GCS)
      · objetos datetime/time
    '--'/''/None/inválido → None.
    """
    if time_str is None:
        return None
    # datetime / time
    if hasattr(time_str, "hour") and hasattr(time_str, "minute"):
        return int(time_str.hour) * 60 + int(time_str.minute)
    s = str(time_str).strip()
    if not s or ":" not in s:
        return None
    # quedarnos con la porción de hora si viene un datetime completo
    if " " in s:
        s = s.split(" ")[-1]
    if "T" in s:
        s = s.split("T")[-1]
    parts = s.split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None


def _fmt_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _franja_label(time_str: Any) -> Optional[str]:
    """Etiqueta de franja de 30 min alineada a :00/:30 (ej. '09:30-10:00')."""
    mins = _to_minutes(time_str)
    if mins is None:
        return None
    start = (mins // 30) * 30
    return f"{_fmt_hhmm(start)}-{_fmt_hhmm(start + 30)}"


# Rangos del histograma MAE/MFE (PRD §5)
_MAE_MFE_BUCKETS = ["0-5", "5-10", "10-15", "15-20", "20-30", "30-50", ">50"]


def _bucket(v: float) -> str:
    if v < 5:
        return "0-5"
    if v < 10:
        return "5-10"
    if v < 15:
        return "10-15"
    if v < 20:
        return "15-20"
    if v < 30:
        return "20-30"
    if v < 50:
        return "30-50"
    return ">50"


def _distribution(records: List[Dict[str, Any]], key: str) -> Dict[str, float]:
    """% de records por franja de 30 min sobre el campo de tiempo `key`."""
    labels = [_franja_label(r.get(key)) for r in records]
    labels = [lab for lab in labels if lab is not None]
    total = len(labels)
    if total == 0:
        return {}
    counts: Dict[str, int] = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    # ordenado por hora de inicio de la franja
    out = {lab: round(cnt / total * 100, 4) for lab, cnt in counts.items()}
    return dict(sorted(out.items(), key=lambda kv: kv[0]))


def _histogram(values: List[float]) -> Dict[str, Any]:
    """Histograma + percentiles + media para una serie MAE o MFE."""
    if not values:
        return {
            "buckets": {b: 0.0 for b in _MAE_MFE_BUCKETS},
            "p25": 0.0, "p50": 0.0, "p75": 0.0, "mean": 0.0,
        }
    total = len(values)
    counts = {b: 0 for b in _MAE_MFE_BUCKETS}
    for v in values:
        counts[_bucket(v)] += 1
    buckets = {b: round(counts[b] / total * 100, 4) for b in _MAE_MFE_BUCKETS}
    xs = sorted(values)
    return {
        "buckets": buckets,
        "p25": round(_quantile(xs, 0.25), 4),
        "p50": round(_quantile(xs, 0.50), 4),
        "p75": round(_quantile(xs, 0.75), 4),
        "mean": round(_mean(values), 4),
    }


# ── Filtros de calidad de universo (Patch v2.1 §01) ─────────────────────────

QUALITY_GAP_MAX_PCT = 400.0           # §01.2
QUALITY_PMH_GAP_MAX_PCT = 400.0      # §01.2 — outliers de PM High Gap distorsionan medias
BLACK_SWAN_SPIKE_MAX_PCT = 300.0      # §01.3 (evalúa max_spike_5m_pct del derivado)
REVERSE_SPLIT_LOOKBACK_DAYS = 5       # §01.1, días naturales


def _rec_date_str(r: Dict[str, Any]) -> str:
    return str(r.get("timestamp"))[:10]


def _rec_date(r: Dict[str, Any]):
    from datetime import datetime
    return datetime.strptime(_rec_date_str(r), "%Y-%m-%d").date()


def build_split_index(splits: Optional[Iterable[Dict[str, Any]]]) -> Tuple[Dict[str, list], Dict[str, set]]:
    """(reverse_by_ticker, anyday_by_ticker) a partir de filas de splits.

    reverse_by_ticker: ticker → [execution_date (date)] solo reverse (split_to < split_from).
    anyday_by_ticker:  ticker → {execution_date} de CUALQUIER split (paridad con la
    exclusión same-day que el cold path ya hacía en SQL, query_service.py).
    Filas sin ratio (tabla antigua) cuentan como any-day pero no como reverse.
    """
    from datetime import date as _date, datetime as _dt
    reverse: Dict[str, list] = {}
    anyday: Dict[str, set] = {}
    for s in splits or []:
        tk = str(s.get("ticker") or "").upper()
        ed = s.get("execution_date")
        if not tk or ed is None:
            continue
        if isinstance(ed, _dt):
            ed = ed.date()
        elif not isinstance(ed, _date):
            try:
                ed = _dt.strptime(str(ed)[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
        anyday.setdefault(tk, set()).add(ed)
        sf, st = s.get("split_from"), s.get("split_to")
        try:
            if sf is not None and st is not None and float(st) < float(sf):
                reverse.setdefault(tk, []).append(ed)
        except (TypeError, ValueError):
            pass
    return reverse, anyday


def apply_quality_filters(
    records: List[Dict[str, Any]],
    *,
    splits: Optional[Iterable[Dict[str, Any]]] = None,
    valid_tickers: Optional[Set[str]] = None,
    black_swan_available: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Punto ÚNICO de exclusión del universo (Patch v2.1 §01). Devuelve
    (records_limpios, contadores) — los contadores van al payload como
    `quality_filters` (transparencia, principio 00: nada silencioso).

    Orden de evaluación por record (se cuenta solo el primer motivo):
      tipo de ticker → gap>1000 → reverse split ≤5d → black swan.
    Black swan usa r["max_spike_5m_pct"] (inyectado por merge_derived); si el
    derivado no está disponible se reporta None (no evaluado, fail-open).
    """
    from datetime import timedelta
    reverse_idx, anyday_idx = build_split_index(splits)
    lookback = timedelta(days=REVERSE_SPLIT_LOOKBACK_DAYS)

    counters = {
        "excluded_ticker_type": 0,
        "excluded_gap_gt_1000": 0,
        "excluded_same_day_split": 0,
        "excluded_reverse_split": 0,
        "excluded_black_swan": 0 if black_swan_available else None,
    }
    kept: List[Dict[str, Any]] = []
    for r in records:
        tk = str(r.get("ticker") or "").upper()

        if valid_tickers is not None and tk not in valid_tickers:
            counters["excluded_ticker_type"] += 1
            continue

        if safe_float(r.get("gap_pct")) > QUALITY_GAP_MAX_PCT:
            counters["excluded_gap_gt_400"] += 1
            continue

        if safe_float(r.get("pmh_gap_pct")) > QUALITY_PMH_GAP_MAX_PCT:
            counters["excluded_pmh_gap_gt_400"] += 1
            continue

        if tk in anyday_idx or tk in reverse_idx:
            try:
                d = _rec_date(r)
            except ValueError:
                d = None
            if d is not None:
                if d in anyday_idx.get(tk, ()):
                    counters["excluded_same_day_split"] += 1
                    continue
                # reverse en (d−5, d]: el día de ejecución contamina el gap
                # (prev_close pre-split vs precio post-split en lake as-traded)
                # y los 4 días siguientes dan margen ante ajustes tardíos del proveedor.
                if any(d - lookback < ed <= d for ed in reverse_idx.get(tk, ())):
                    counters["excluded_reverse_split"] += 1
                    continue

        if black_swan_available:
            spike = r.get("max_spike_5m_pct")
            if spike is not None and not (isinstance(spike, float) and math.isnan(spike)) \
                    and safe_float(spike) > BLACK_SWAN_SPIKE_MAX_PCT:
                counters["excluded_black_swan"] += 1
                continue

        kept.append(r)
    return kept, counters


def merge_derived(records: List[Dict[str, Any]], derived_map: Optional[Dict[Tuple[str, str], Dict[str, Any]]]) -> None:
    """Inyecta in-place m0_return_pct / m90_return_pct / max_spike_5m_pct desde el
    derivado ma_daily, clave (ticker, 'YYYY-MM-DD'). Sin fila derivada → no toca el record."""
    if not derived_map:
        return
    for r in records:
        row = derived_map.get((str(r.get("ticker") or "").upper(), _rec_date_str(r)))
        if row:
            for k in ("m0_return_pct", "m90_return_pct", "max_spike_5m_pct"):
                if row.get(k) is not None:
                    r[k] = row[k]


# ── KPIs (MA-01) ─────────────────────────────────────────────────────────────

def compute_kpis(records: List[Dict[str, Any]], fade_threshold: float = 50.0) -> Dict[str, Any]:
    """
    KPIs del header (Patch v2.1 §02/§03/§07). `records` ya viene filtrado al universo
    (gap >= filtro_gap + filtros de calidad). `fade_threshold` define el subuniverso
    del KPI avg_fade_from_pmh (gap_pct >= umbral, default 50) — NO afecta a fade_windows.

    Cambios v2.1: pm_high_average ($) → pm_high_gap_pct (%); + gappers_count_pm
    (pmh_gap_pct>0, "subió en pre"); max_fade_from_pmh eliminado (§03: un extremo
    puntual revienta la métrica); close_lt_vwap_pct reservado null (v1.2).
    """
    n = len(records)

    gaps = [safe_float(r.get("gap_pct")) for r in records]
    # PM High Gap % sobre gappers con pre-market real (pm_high>0). pmh_gap_pct
    # viene precalculada del processor: (pm_high − prev_close)/prev_close × 100.
    pmh_gaps = [safe_float(r.get("pmh_gap_pct")) for r in records if safe_float(r.get("pm_high")) > 0]
    pm_count = sum(1 for r in records if safe_float(r.get("pmh_gap_pct")) > 0)

    # Close Red %: rth_close < rth_open directo (day_return_pct del lake no es fiable)
    close_red_n = sum(1 for r in records if is_close_red(r))

    # Avg Fade desde PMH a EOD, subuniverso gap_pct >= fade_threshold
    fade_universe = [r for r in records if safe_float(r.get("gap_pct")) >= fade_threshold]
    fades: List[float] = []
    for r in fade_universe:
        pmh = safe_float(r.get("pm_high"))
        if pmh <= 0:
            continue
        fades.append((pmh - safe_float(r.get("close_1559"))) / pmh * 100)

    return {
        "gappers_count": {"value": float(n)},
        "gappers_count_pm": {"value": float(pm_count)},
        "avg_gap_pct": {"value": round(_mean(gaps), 4) if gaps else None},
        "pm_high_gap_pct": {"value": round(_mean(pmh_gaps), 4) if pmh_gaps else None},
        "close_red_pct": {"value": round(close_red_n / n * 100, 4) if n else None},
        "close_lt_vwap_pct": {"value": None},  # v1.2 (day_vwap)
        "avg_fade_from_pmh": {"value": round(_mean(fades), 4) if fades else None},
    }


# ── Ventanas de Fade (Patch v2.1 §04 — sustituye a MAE/MFE) ──────────────────

# franja → columna con el retorno del close asof esa hora vs rth_open.
# m30/m60 son columnas históricas de daily_metrics (processor_service.get_return_at);
# m0/m90 vienen del derivado ma_daily (merge_derived) con la MISMA semántica asof.
_FADE_FRANJAS: List[Tuple[str, str]] = [
    ("09:30", "m0_return_pct"),
    ("10:00", "m30_return_pct"),
    ("10:30", "m60_return_pct"),
    ("11:00", "m90_return_pct"),
]


def _num_or_none(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def is_close_red(r: Dict[str, Any]) -> bool:
    """Close Red ≡ rth_close < rth_open, comparado DIRECTAMENTE sobre las columnas.

    NO usar day_return_pct del lake: la variante del catchup no es
    (rth_close−rth_open)/rth_open (auditado 08-jul-2026: AHMA rth 2.80→1.47
    con day_return_pct=+36.1 → un Close Red de 4-6% imposible). Fallback a
    day_return_pct<0 solo si faltan las columnas rth.
    """
    rth_open = safe_float(r.get("rth_open"))
    rth_close = safe_float(r.get("rth_close"))
    if rth_open > 0 and rth_close > 0:
        return rth_close < rth_open
    return safe_float(r.get("day_return_pct")) < 0


def compute_fade_windows(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Caída media de los gappers por franja de entrada (§04).

    RTH por franja F: entrada = rth_open × (1 + m{F}_return_pct/100) — es decir, el
    close de la última vela ≤ F (semántica asof de get_return_at); salida = close_1559.
    fade = (entrada − salida)/entrada × 100; entrada ≤ 0 → se excluye el gapper en F.
    pct_favorable = % de gappers válidos con fade > 0 (bajó de la franja al cierre).

    PM: entrada = pm_high, salida = close_1559, sobre el UNIVERSO COMPLETO — a
    diferencia del KPI avg_fade_from_pmh, que usa el subuniverso fade_threshold.

    Si ninguna fila trae la columna de una franja (derivado ma_daily sin backfill
    para el periodo), la franja emite pending_backfill=True en vez de un 0 falso.
    """
    rth = []
    for franja, col in _FADE_FRANJAS:
        fades: List[float] = []
        col_seen = False
        for r in records:
            m = _num_or_none(r.get(col))
            if m is None:
                continue
            col_seen = True
            rth_open = safe_float(r.get("rth_open"))
            entrada = rth_open * (1 + m / 100.0)
            if rth_open <= 0 or entrada <= 0:
                continue
            fades.append((entrada - safe_float(r.get("close_1559"))) / entrada * 100)
        if records and not col_seen:
            rth.append({"franja": franja, "avg_fade_pct": None, "pct_favorable": None,
                        "n": 0, "pending_backfill": True})
            continue
        rth.append({
            "franja": franja,
            "avg_fade_pct": round(_mean(fades), 4) if fades else None,
            "pct_favorable": round(sum(1 for f in fades if f > 0) / len(fades) * 100, 4) if fades else None,
            "n": len(fades),
        })

    pm_fades: List[float] = []
    for r in records:
        pmh = safe_float(r.get("pm_high"))
        if pmh <= 0:
            continue
        pm_fades.append((pmh - safe_float(r.get("close_1559"))) / pmh * 100)
    pm = {
        "avg_fade_pct": round(_mean(pm_fades), 4) if pm_fades else None,
        "pct_favorable": round(sum(1 for f in pm_fades if f > 0) / len(pm_fades) * 100, 4) if pm_fades else None,
        "n": len(pm_fades),
    }
    return {"rth": rth, "pm": pm}


# ── Recent Gaps Up (MA-06) ───────────────────────────────────────────────────

def map_recent_gaps(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mapea filas crudas de daily_metrics a las 9 columnas de la tabla MA-06."""
    out = []
    for r in records:
        out.append({
            "ticker": r.get("ticker", ""),
            "date": str(r.get("timestamp"))[:10],
            "gap_at_open_pct": safe_float(r.get("gap_pct")),
            "open": safe_float(r.get("rth_open")),
            "vol_rth": safe_float(r.get("rth_volume")),
            "vol_pm": safe_float(r.get("pm_volume")),
            "hod": safe_float(r.get("rth_high")),
            "pmh": safe_float(r.get("pm_high")),
            "close_red": is_close_red(r),
        })
    return out


# ── ensamblado completo ──────────────────────────────────────────────────────

def compute_market_analysis(
    records: List[Dict[str, Any]],
    fade_threshold: float = 50.0,
) -> Dict[str, Any]:
    """
    Ensambla el payload analítico (sin deltas vs periodo anterior) a partir de los
    records YA pasados por apply_quality_filters. Las deltas y quality_filters se
    añaden en get_market_analysis (capa con BD).

    `records` se mantiene en el payload aunque la UI ya no pinte tabla (§05):
    lo consume el contexto de página de Edgie (muestra acotada en frontend).
    """
    return {
        "records": map_recent_gaps(records),
        "kpis": compute_kpis(records, fade_threshold=fade_threshold),
        "distributions": {
            "hod_time": _distribution(records, "hod_time"),
            "lod_time": _distribution(records, "lod_time"),
            "pmh_time": _distribution(records, "pm_high_time"),
        },
        "fade_windows": compute_fade_windows(records),
    }


# ── capa con BD (orquestación) ───────────────────────────────────────────────
# Imports de BD perezosos (dentro de las funciones) para que el módulo siga siendo
# importable/testeable sin conexión.

_PERIOD_DAYS = {
    "1w": 7, "1m": 30, "3m": 90, "6m": 180, "1y": 365,
    # ventanas cortas para los toggles independientes de Time Distribution (MA-02)
    "5d": 5, "30d": 30, "90d": 90,
}

# KPIs que llevan delta vs periodo anterior.
_DELTA_KPIS = ("gappers_count", "gappers_count_pm", "avg_gap_pct",
               "pm_high_gap_pct", "close_red_pct", "avg_fade_from_pmh")


def _as_date(v):
    from datetime import date, datetime
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def _resolve_period_dates(latest, filters):
    """
    (start, end_excl, end_label) a partir de la última fecha con datos `latest`.
    Rango explícito start/end → end inclusivo (end_excl = end+1d). Preset period → ventana relativa.
    Ventanas semiabiertas [start, end_excl) consistentes entre actual y anterior.
    """
    from datetime import timedelta
    sd = filters.get("start_date") or filters.get("date_from")
    ed = filters.get("end_date") or filters.get("date_to")
    if sd and ed:
        start, end_incl = _as_date(sd), _as_date(ed)
        return start, end_incl + timedelta(days=1), end_incl
    days = _PERIOD_DAYS.get(str(filters.get("period", "1m")).lower(), 30)
    end_excl = latest + timedelta(days=1)
    return end_excl - timedelta(days=days), end_excl, latest


def _hot_records(df, filters, limit):
    """
    Filtra el hot cache (DataFrame en RAM con gap_pct>=10 y todas las columnas de daily_metrics)
    en pandas → lista de dicts. Sirve el caso común (gap alto) en <100ms sin tocar GCS.
    Nota: el hot path no aplica el filtro de tipo de ticker (CS/ADRC/OS) — igual que el /screener
    original, prioriza latencia; el cold path (GCS) sí lo aplica vía build_screener_query.
    """
    import pandas as pd
    r = df
    eff_gap = max(safe_float(filters.get("min_gap")), safe_float(filters.get("min_gap_at_open_pct")))
    if eff_gap:
        r = r[r["gap_pct"] >= eff_gap]
    mg = filters.get("max_gap") or filters.get("max_gap_at_open_pct")
    if mg not in (None, ""):
        r = r[r["gap_pct"] <= safe_float(mg)]
    if filters.get("min_volume"):
        r = r[r["volume"] >= safe_float(filters["min_volume"])]
    if filters.get("max_volume"):
        r = r[r["volume"] <= safe_float(filters["max_volume"])]
    if filters.get("min_pm_volume"):
        r = r[r["pm_volume"] >= safe_float(filters["min_pm_volume"])]
    if filters.get("min_open"):
        r = r[r["rth_open"] >= safe_float(filters["min_open"])]
    if filters.get("max_open"):
        r = r[r["rth_open"] <= safe_float(filters["max_open"])]
    if filters.get("min_pmh_gap"):
        r = r[r["pmh_gap_pct"] >= safe_float(filters["min_pmh_gap"])]
    if filters.get("max_pmh_gap"):
        r = r[r["pmh_gap_pct"] <= safe_float(filters["max_pmh_gap"])]
    # Volumen del día = PM + RTH (principio 00 del Patch v2.1: NO usar `volume`,
    # que incluye after-hours, para "volumen del día").
    if filters.get("min_day_volume"):
        r = r[(r["pm_volume"] + r["rth_volume"]) >= safe_float(filters["min_day_volume"])]
    # close_red server-side (v2.1 §05: al desaparecer la tabla, el filtro afecta a
    # KPIs/módulos). rth_close<rth_open directo — ver is_close_red.
    cr = str(filters.get("close_red") or "").lower()
    if cr in ("yes", "no"):
        mask = (r["rth_close"] < r["rth_open"]) & (r["rth_open"] > 0) & (r["rth_close"] > 0)
        r = r[mask if cr == "yes" else ~mask]
    sd, ed = filters.get("start_date"), filters.get("end_date")
    if sd:
        r = r[r["timestamp"] >= pd.Timestamp(str(sd))]
    if ed:
        r = r[r["timestamp"] < pd.Timestamp(str(ed))]
    tk = filters.get("ticker")
    if tk:
        r = r[r["ticker"].astype(str) == str(tk).upper()]
    r = r.sort_values(["timestamp", "gap_pct"], ascending=[False, False]).head(limit)
    return r.to_dict("records")


def _fetch_records(con, filters, limit):
    from app.services.query_service import build_screener_query
    rec_query, sql_p, _, _, _, _ = build_screener_query(filters, limit=limit)
    cur = con.execute(rec_query, sql_p)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _load_quality_inputs():
    """(splits_records, valid_tickers, derived_map) desde los caches de referencia.
    Cada pieza es fail-open (None) si su fuente no está disponible: el análisis
    sale igualmente y quality_filters refleja qué se pudo evaluar."""
    splits = None
    try:
        from app.services.cache_service import get_effective_splits_df
        df = get_effective_splits_df()
        if df is not None and not df.empty:
            splits = df.to_dict("records")
    except Exception as e:
        print(f"[WARN] MA sin splits para filtros de calidad: {e}")

    valid = None
    try:
        from app.services.cache_service import get_tickers_df
        tdf = get_tickers_df()
        if tdf is not None and not tdf.empty:
            valid = set(tdf["ticker"].astype(str).str.upper())
    except Exception as e:
        print(f"[WARN] MA sin tabla de tickers para paridad de tipos: {e}")

    derived_map = None
    try:
        from app.services.cache_service import get_ma_derived_df
        ddf = get_ma_derived_df()
        if ddf is not None and not ddf.empty:
            derived_map = {
                (str(t).upper(), str(d)): {
                    "m0_return_pct": m0, "m90_return_pct": m90, "max_spike_5m_pct": spike,
                }
                for t, d, m0, m90, spike in zip(
                    ddf["ticker"], ddf["date"], ddf["m0_return_pct"],
                    ddf["m90_return_pct"], ddf["max_spike_5m_pct"],
                )
            }
    except Exception as e:
        print(f"[WARN] MA sin derivado ma_daily: {e}")

    return splits, valid, derived_map


def get_market_analysis(filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Orquestación con BD (router fino → lógica aquí). Resuelve periodo, trae records del
    periodo actual y del anterior equivalente (vía build_screener_query), calcula el payload
    analítico y las deltas de KPI. `source` indica el proveedor de datos.
    """
    import os
    from datetime import date, timedelta
    from app.database import get_db_connection

    fade_threshold = safe_float(filters.get("fade_threshold")) or 50.0
    limit = int(safe_float(filters.get("limit")) or 5000)
    effective_gap = max(safe_float(filters.get("min_gap")), safe_float(filters.get("min_gap_at_open_pct")))

    # Hot cache (gap_pct>=10 en RAM) para el caso común → <100ms sin tocar GCS.
    hot_df = None
    try:
        from app.services.cache_service import get_hot_daily_df
        hot_df = get_hot_daily_df()
    except Exception:
        hot_df = None
    use_hot = hot_df is not None and getattr(hot_df, "empty", True) is False and effective_gap >= 10.0

    # Claves propias de Market Analysis que NO son columnas de daily_metrics (no deben ir al SQL).
    base = {k: v for k, v in filters.items() if k not in ("period", "fade_threshold")}

    con = None
    try:
        latest = None
        if use_hot:
            try:
                import pandas as pd
                latest = pd.Timestamp(hot_df["timestamp"].max()).date()
            except Exception:
                latest = None
        if latest is None:
            con = get_db_connection(read_only=True)
            row = con.execute("SELECT CAST(MAX(timestamp) AS DATE) FROM daily_metrics").fetchone()
            latest = row[0] if row and row[0] else date.today()
            if isinstance(latest, str):
                latest = _as_date(latest)

        start, end_excl, end_label = _resolve_period_dates(latest, filters)
        duration = max((end_excl - start).days, 1)
        prev_start = start - timedelta(days=duration)

        cur_filters = {**base, "start_date": str(start), "end_date": str(end_excl)}
        prev_filters = {**base, "start_date": str(prev_start), "end_date": str(start)}

        if use_hot:
            cur_records = _hot_records(hot_df, cur_filters, limit)
            prev_records = _hot_records(hot_df, prev_filters, limit)
            source = "hot_cache"
        else:
            if con is None:
                con = get_db_connection(read_only=True)
            cur_records = _fetch_records(con, cur_filters, limit)
            prev_records = _fetch_records(con, prev_filters, limit)
            source = os.getenv("DB_PROVIDER", "motherduck").lower()

        # Patch v2.1 §01 — calidad de universo en AMBOS periodos (los deltas
        # comparan universos igual de limpios) y con paridad hot/cold.
        splits, valid_tickers, derived_map = _load_quality_inputs()
        merge_derived(cur_records, derived_map)
        merge_derived(prev_records, derived_map)
        bs_available = derived_map is not None
        cur_records, quality = apply_quality_filters(
            cur_records, splits=splits, valid_tickers=valid_tickers, black_swan_available=bs_available)
        prev_records, _ = apply_quality_filters(
            prev_records, splits=splits, valid_tickers=valid_tickers, black_swan_available=bs_available)

        payload = compute_market_analysis(cur_records, fade_threshold=fade_threshold)
        prev_kpis = compute_kpis(prev_records, fade_threshold=fade_threshold)
        for key in _DELTA_KPIS:
            payload["kpis"][key]["prev"] = prev_kpis[key]["value"]

        payload["quality_filters"] = quality
        payload["source"] = source
        payload["period"] = {"start": str(start), "end": str(end_label)}
        return payload
    finally:
        if con:
            con.close()


# ── MA-04 · Avg Change from Open (12 meses) ──────────────────────────────────

import threading as _threading

_CURVES_CON_LOCK = _threading.Lock()
_curves_con = None


def _get_curves_connection():
    """Conexión DuckDB mínima (httpfs + secret GCS, SIN vistas del lake) cacheada a
    nivel de módulo — el fichero de curvas es un único parquet pequeño."""
    global _curves_con
    import os
    import duckdb
    with _CURVES_CON_LOCK:
        if _curves_con is not None:
            try:
                _curves_con.execute("SELECT 1")
                return _curves_con
            except Exception:
                _curves_con = None
        con = duckdb.connect()
        con.execute("SET enable_progress_bar = false; INSTALL httpfs; LOAD httpfs;")
        key, secret = os.getenv("GCS_HMAC_KEY"), os.getenv("GCS_HMAC_SECRET")
        if key and secret:
            con.execute(f"CREATE SECRET curves_gcs (TYPE GCS, KEY_ID '{key}', SECRET '{secret}');")
        _curves_con = con
        return con


_MES_ABBR = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
             "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _month_label(month_str: str, current_year: int) -> str:
    """'2026-06' → 'Jun' (+ ''YY' si el año difiere del actual)."""
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
    except (ValueError, IndexError):
        return month_str
    lab = _MES_ABBR[m] if 1 <= m <= 12 else month_str
    return lab if y == current_year else f"{lab} '{str(y)[2:]}"


def get_avg_change_from_open(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    MA-04 §4.2 con el fix del Patch v2.1 (§06): las curvas se leen del parquet
    derivado `cold_storage/derived/ma_monthly_curves.parquet`, precalculado por
    scripts/backfill_ma_derived.py sobre el UNIVERSO ESTÁNDAR (gap≥30, vol día≥1M,
    filtros de calidad §01) — la UI lo etiqueta. Los filtros del request se ignoran
    (decisión Q3 del patch: es lo que hace el módulo viable en modo GCS).

    Por qué: la query original juntaba 12 meses de intraday_1m SIN poda de
    particiones → scan del lake entero por red → timeout ("Sin datos de perfil
    mensual"). Medido 07-jul-2026: 16,2 s para UNA semana YA podada. El derivado
    son ~300 filas: <1 s. Si el parquet no existe aún → [] con log (empty state).
    """
    import os
    from datetime import date

    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")

    try:
        if provider == "local":
            from app.database import get_db_connection
            con = get_db_connection(read_only=True)
            rows = con.execute(
                "SELECT month, franja, avg_change, avg_gap_pct FROM ma_monthly_curves "
                "ORDER BY month, franja").fetchall()
        else:
            # Conexión ligera dedicada: get_db_connection inicializaría TODAS las
            # vistas del lake en el thread nuevo (resolución de schemas de los globs
            # de GCS, decenas de segundos — auditado 08-jul-2026 con timeouts de 20s
            # desde el navegador). Aquí solo hace falta leer UN parquet pequeño.
            con = _get_curves_connection()
            with _CURVES_CON_LOCK:
                rows = con.execute(
                    f"SELECT month, franja, avg_change, avg_gap_pct FROM read_parquet("
                    f"'gs://{bucket}/cold_storage/derived/ma_monthly_curves.parquet') "
                    f"ORDER BY month, franja").fetchall()
    except Exception as e:
        print(f"[WARN] MA-04 sin curvas derivadas ({e}); devolviendo []. "
              f"Generar con: python scripts/backfill_ma_derived.py")
        return []

    current_year = date.today().year
    months: Dict[str, Dict[str, Any]] = {}
    gaps: Dict[str, float] = {}
    for month, franja, avg_change, avg_gap in rows:
        months.setdefault(month, {"month": month, "points": []})
        months[month]["points"].append({"time": str(franja), "avg_change": safe_float(avg_change)})
        gaps[month] = safe_float(avg_gap)

    out = []
    for month in sorted(months.keys()):
        item = months[month]
        item["avg_gap_pct"] = gaps.get(month, 0.0)
        item["label"] = _month_label(month, current_year)
        out.append(item)
    return out[-12:]
