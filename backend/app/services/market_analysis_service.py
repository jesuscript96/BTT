"""
Market Analysis service — agregación en Python puro sobre los gappers ya filtrados.

Implementa los módulos del MVP de docs/market-analysis/PRD.md:
  · MA-01 KPIs (K1-K4, K6, K7)         · MA-02 Time Distribution (HOD/LOD/PMH)
  · MA-05 MAE/MFE (PM/RTH)             · MA-06 Recent Gaps Up (mapeo de records)

Diseño (anclado en GUIA_PRD_EJECUTABLE §6.1 "routers finos, services gordos"):
  El filtrado/selección pesado se queda en query_service.build_screener_query (SQL sobre
  daily_metrics). Este módulo recibe los dicts de fila resultantes y calcula la estadística
  descriptiva en Python, para que la matemática sea unit-testable SIN BD viva
  (los ejemplos numéricos del PRD §5 se vuelven asserts en test_market_analysis.py).

Notas de alcance MVP:
  · close_lt_vwap_pct → None (Fase 2: depende de day_vwap, ver PRD §7).
  · País/Sector/Float → Fase 2 (no se calculan aquí).

Nomenclatura: las claves de fila son las columnas literales de daily_metrics
(ver processor_service.process_daily_metrics): gap_pct, pm_high, pm_low, pm_high_time,
hod_time, lod_time, rth_open, rth_high, rth_low, rth_volume, pm_volume, close_1559,
day_return_pct, prev_close, timestamp, ticker.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


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


# ── KPIs (MA-01) ─────────────────────────────────────────────────────────────

def compute_kpis(records: List[Dict[str, Any]], fade_threshold: float = 50.0) -> Dict[str, Any]:
    """
    KPIs del PRD §5. `records` ya viene filtrado al universo de gappers (gap >= filtro_gap).
    `fade_threshold` define el subuniverso de K6/K7 (gap_pct >= umbral, default 50).
    """
    n = len(records)

    gaps = [safe_float(r.get("gap_pct")) for r in records]
    pm_highs = [safe_float(r.get("pm_high")) for r in records if safe_float(r.get("pm_high")) > 0]

    # K4 Close Red %: day_return_pct < 0  (≡ rth_close < rth_open)
    close_red_n = sum(1 for r in records if safe_float(r.get("day_return_pct")) < 0)

    # K6/K7 Fade desde PMH a EOD, subuniverso gap_pct >= fade_threshold
    fade_universe = [r for r in records if safe_float(r.get("gap_pct")) >= fade_threshold]
    fades: List[Dict[str, Any]] = []
    for r in fade_universe:
        pmh = safe_float(r.get("pm_high"))
        if pmh <= 0:
            continue
        eod = safe_float(r.get("close_1559"))
        fades.append({
            "fade": (pmh - eod) / pmh * 100,
            "ticker": r.get("ticker"),
            "date": str(r.get("timestamp"))[:10],
        })
    max_fade = max(fades, key=lambda f: f["fade"]) if fades else None

    return {
        "gappers_count": {"value": float(n)},
        "avg_gap_pct": {"value": round(_mean(gaps), 4) if gaps else None},
        "pm_high_average": {"value": round(_mean(pm_highs), 4) if pm_highs else None},
        "close_red_pct": {"value": round(close_red_n / n * 100, 4) if n else None},
        "close_lt_vwap_pct": {"value": None},  # Fase 2 (day_vwap)
        "avg_fade_from_pmh": {
            "value": round(_mean([f["fade"] for f in fades]), 4) if fades else None
        },
        "max_fade_from_pmh": {
            "value": round(max_fade["fade"], 4) if max_fade else None,
            "ticker": max_fade["ticker"] if max_fade else None,
            "date": max_fade["date"] if max_fade else None,
        },
    }


# ── MAE / MFE (MA-05) ────────────────────────────────────────────────────────

def compute_mae_mfe(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    PRD §5. RTH: ref rth_open (open estricto 09:30, Q1). PM: ref prev_close.
    MAE = excursión adversa (subida), MFE = excursión favorable (caída). Clamp a 0.
    """
    rth_mae, rth_mfe, pm_mae, pm_mfe = [], [], [], []
    for r in records:
        rth_open = safe_float(r.get("rth_open"))
        if rth_open > 0:
            rth_mae.append(max(0.0, (safe_float(r.get("rth_high")) - rth_open) / rth_open * 100))
            rth_mfe.append(max(0.0, (rth_open - safe_float(r.get("rth_low"))) / rth_open * 100))
        prev_close = safe_float(r.get("prev_close"))
        pm_high = safe_float(r.get("pm_high"))
        if prev_close > 0 and pm_high > 0:
            pm_mae.append(max(0.0, (pm_high - prev_close) / prev_close * 100))
            pm_low = safe_float(r.get("pm_low"))
            pm_mfe.append(max(0.0, (prev_close - pm_low) / prev_close * 100))
    return {
        "rth": {"mae": _histogram(rth_mae), "mfe": _histogram(rth_mfe)},
        "pm": {"mae": _histogram(pm_mae), "mfe": _histogram(pm_mfe)},
    }


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
            "close_red": safe_float(r.get("day_return_pct")) < 0,
        })
    return out


# ── ensamblado completo ──────────────────────────────────────────────────────

def compute_market_analysis(
    records: List[Dict[str, Any]],
    fade_threshold: float = 50.0,
) -> Dict[str, Any]:
    """
    Ensambla el payload analítico (sin deltas vs periodo anterior) a partir de los
    records filtrados. Las deltas se añaden en get_market_analysis (capa con BD).
    """
    return {
        "records": map_recent_gaps(records),
        "kpis": compute_kpis(records, fade_threshold=fade_threshold),
        "distributions": {
            "hod_time": _distribution(records, "hod_time"),
            "lod_time": _distribution(records, "lod_time"),
            "pmh_time": _distribution(records, "pm_high_time"),
        },
        "mae_mfe": compute_mae_mfe(records),
    }


# ── capa con BD (orquestación) ───────────────────────────────────────────────
# Imports de BD perezosos (dentro de las funciones) para que el módulo siga siendo
# importable/testeable sin conexión.

_PERIOD_DAYS = {
    "1w": 7, "1m": 30, "3m": 90, "6m": 180, "1y": 365,
    # ventanas cortas para los toggles independientes de Time Distribution (MA-02)
    "5d": 5, "30d": 30, "90d": 90,
}

# KPIs que llevan delta vs periodo anterior (max_fade lleva ticker/date, no delta).
_DELTA_KPIS = ("gappers_count", "avg_gap_pct", "pm_high_average",
               "close_red_pct", "avg_fade_from_pmh")


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

        payload = compute_market_analysis(cur_records, fade_threshold=fade_threshold)
        prev_kpis = compute_kpis(prev_records, fade_threshold=fade_threshold)
        for key in _DELTA_KPIS:
            payload["kpis"][key]["prev"] = prev_kpis[key]["value"]

        payload["source"] = source
        payload["period"] = {"start": str(start), "end": str(end_label)}
        return payload
    finally:
        if con:
            con.close()


# ── MA-04 · Avg Change from Open (12 meses) ──────────────────────────────────

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
    PRD MA-04 §4.2. Para cada uno de los últimos 12 meses naturales (independiente del
    selector de periodo global), curva media `change_from_open = (close_bar - rth_open)/rth_open`
    por franja de 30 min de 04:00 a 16:00, más la línea de referencia `avg_gap_pct` del mes.

    DB-bound: agrega `intraday_1m` contra el set de gappers del periodo (build_screener_query).
    """
    from datetime import date, timedelta
    from app.database import get_db_connection
    from app.services.query_service import build_screener_query

    con = None
    try:
        con = get_db_connection(read_only=True)
        row = con.execute("SELECT CAST(MAX(timestamp) AS DATE) FROM daily_metrics").fetchone()
        end = row[0] if row and row[0] else date.today()
        if isinstance(end, str):
            end = _as_date(end)
        # primer día del mes 11 meses atrás → ventana de 12 meses naturales
        total = end.year * 12 + (end.month - 1) - 11
        start = date(total // 12, total % 12 + 1, 1)

        f = {k: v for k, v in filters.items() if k not in ("period", "fade_threshold")}
        f["start_date"] = str(start)
        f["end_date"] = str(end + timedelta(days=1))
        rec_query, sql_p, _, _, _, _ = build_screener_query(f, limit=500000)

        # minutos del día → inicio de franja de 30 min (alineado :00/:30)
        mins_expr = ("(CAST(extract(hour FROM i.timestamp) AS INTEGER) * 60 "
                     "+ CAST(extract(minute FROM i.timestamp) AS INTEGER))")
        agg_sql = f"""
            WITH g AS (
                SELECT ticker, CAST(timestamp AS DATE) AS d, rth_open
                FROM ( {rec_query} )
                WHERE rth_open > 0
            ),
            bars AS (
                SELECT strftime(i.timestamp, '%Y-%m') AS month,
                       (({mins_expr}) // 30) * 30 AS fb,
                       (i.close - g.rth_open) / g.rth_open * 100 AS pct
                FROM intraday_1m i
                JOIN g ON i.ticker = g.ticker AND i.date = g.d
                WHERE ({mins_expr}) BETWEEN 240 AND 959
            )
            SELECT month,
                   printf('%02d:%02d', fb // 60, fb % 60) AS franja,
                   AVG(pct) AS avg_change
            FROM bars
            GROUP BY month, fb
            ORDER BY month, fb
        """
        rows = con.execute(agg_sql, sql_p).fetchall()

        gap_sql = f"SELECT strftime(timestamp, '%Y-%m') AS month, AVG(gap_pct) FROM ( {rec_query} ) GROUP BY 1"
        gaps = {m: safe_float(v) for m, v in con.execute(gap_sql, sql_p).fetchall()}

        months: Dict[str, Dict[str, Any]] = {}
        for month, franja, avg_change in rows:
            months.setdefault(month, {"month": month, "points": []})
            months[month]["points"].append({"time": franja, "avg_change": safe_float(avg_change)})

        out = []
        for month in sorted(months.keys()):
            item = months[month]
            item["avg_gap_pct"] = gaps.get(month, 0.0)
            item["label"] = _month_label(month, end.year)
            out.append(item)
        return out[-12:]
    finally:
        if con:
            con.close()
