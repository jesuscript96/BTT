"""
Market Analysis — tests de la matemática (Python puro, SIN BD).

Los ejemplos numéricos de los PRDs (docs/market-analysis/PRD.md §5 y
docs/market-analysis/PRD_PATCH_v2.1.md §5) se convierten aquí en asserts.
No requieren MotherDuck/GCS: prueban services/market_analysis_service.py sobre
records sintéticos con las claves literales de daily_metrics.

Ejecutar:  cd backend && python -m pytest tests/test_market_analysis.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.market_analysis_service import (  # noqa: E402
    apply_quality_filters,
    build_split_index,
    compute_fade_windows,
    compute_kpis,
    compute_market_analysis,
    map_recent_gaps,
    merge_derived,
    _quantile,
    _bucket,
    _franja_label,
)

TOL = 1e-3


def _example_record():
    """Fila base del PRD §5 (+ patch v2.1 §5):
    prev_close=10, rth_open=13, pm_high=18, rth_high=14, rth_low=8.5,
    pm_low=11.5, close_1559=9, gap_pct=30, day_return=(9-13)/13=-30.77 → red.
    Closes de vela: 09:30→13.20, 10:00→12.40, 10:30→11.80, 11:00→11.00.
    m30/m60 son columnas históricas de daily_metrics; m0/m90 llegan del derivado.
    """
    return {
        "ticker": "WXYZ", "timestamp": "2026-06-03",
        "gap_pct": 30.0, "pm_high": 18.0, "pm_low": 11.5, "pm_high_time": "07:15",
        "hod_time": "09:42", "lod_time": "15:10",
        "rth_open": 13.0, "rth_high": 14.0, "rth_low": 8.5, "rth_close": 9.0,
        "rth_volume": 8_200_000.0, "pm_volume": 1_500_000.0,
        "close_1559": 9.0, "day_return_pct": -30.769, "prev_close": 10.0,
        "pmh_gap_pct": 80.0,               # (18-10)/10 × 100
        "m30_return_pct": -4.615385,       # close 10:00 = 12.40
        "m60_return_pct": -9.230769,       # close 10:30 = 11.80
    }


def _derived_row():
    """Fila del derivado ma_daily para el record base."""
    return {
        "m0_return_pct": 1.538462,         # close 09:30 = 13.20
        "m90_return_pct": -15.384615,      # close 11:00 = 11.00
        "max_spike_5m_pct": 42.0,
    }


# ── helpers ──────────────────────────────────────────────────────────────────

def test_quantile_linear_interpolation():
    xs = [10.0, 20.0, 30.0, 40.0]
    assert abs(_quantile(xs, 0.5) - 25.0) < TOL
    assert abs(_quantile(xs, 0.25) - 17.5) < TOL
    assert abs(_quantile(xs, 0.75) - 32.5) < TOL


def test_bucket_boundaries():
    assert _bucket(0) == "0-5"
    assert _bucket(5) == "5-10"        # límite inferior va al rango superior
    assert _bucket(49.999) == "30-50"
    assert _bucket(50) == ">50"


def test_franja_label():
    assert _franja_label("09:42") == "09:30-10:00"
    assert _franja_label("07:15") == "07:00-07:30"
    assert _franja_label("15:10") == "15:00-15:30"
    # formato datetime completo de GCS: 'YYYY-MM-DD HH:MM'
    assert _franja_label("2026-06-26 14:58") == "14:30-15:00"
    assert _franja_label("2026-06-26 09:31") == "09:30-10:00"
    assert _franja_label("--") is None
    assert _franja_label("") is None
    assert _franja_label(None) is None


# ── KPIs (MA-01 · patch §02/§03/§07) ─────────────────────────────────────────

def test_kpis_example():
    k = compute_kpis([_example_record()], fade_threshold=30.0)
    assert k["gappers_count"]["value"] == 1.0
    assert k["gappers_count_pm"]["value"] == 1.0        # pmh_gap_pct=80 > 0 → subió en pre
    assert abs(k["avg_gap_pct"]["value"] - 30.0) < TOL
    # PM High Gap % = (18-10)/10 = 80% — en %, no en $ (patch §02)
    assert abs(k["pm_high_gap_pct"]["value"] - 80.0) < TOL
    assert abs(k["close_red_pct"]["value"] - 100.0) < TOL
    # Fade a EOD = (18-9)/18 = 50%
    assert abs(k["avg_fade_from_pmh"]["value"] - 50.0) < TOL
    # Close<VWAP pospuesto (v1.2)
    assert k["close_lt_vwap_pct"]["value"] is None
    # Max Fade eliminado del contrato (patch §03)
    assert "max_fade_from_pmh" not in k
    assert "pm_high_average" not in k


def test_kpis_fade_threshold_excludes_below():
    # gap=30 < umbral default 50 ⇒ subuniverso de fade vacío
    k = compute_kpis([_example_record()], fade_threshold=50.0)
    assert k["avg_fade_from_pmh"]["value"] is None


def test_close_red_ignora_day_return_pct_corrupto():
    # El day_return_pct del lake NO es (rth_close−rth_open)/rth_open (variante del
    # catchup; auditado 08-jul-2026 con Close Red imposible de 4-6%). Close Red
    # debe salir de la comparación directa rth_close < rth_open.
    r = _example_record()
    r["day_return_pct"] = 36.1          # corrupto: positivo pese a rth 13.0 → 9.0
    k = compute_kpis([r], fade_threshold=30.0)
    assert abs(k["close_red_pct"]["value"] - 100.0) < TOL
    assert map_recent_gaps([r])[0]["close_red"] is True
    # fallback a day_return_pct SOLO sin columnas rth
    r2 = _example_record()
    r2["rth_close"] = 0.0
    r2["day_return_pct"] = 5.0
    k2 = compute_kpis([r2], fade_threshold=30.0)
    assert abs(k2["close_red_pct"]["value"] - 0.0) < TOL


def test_kpis_pm_high_gap_excludes_no_pm():
    r1 = _example_record()
    r2 = _example_record()
    r2["pm_high"] = 0.0        # sin datos PM → fuera del promedio y del count PM
    r2["pmh_gap_pct"] = 0.0
    k = compute_kpis([r1, r2], fade_threshold=30.0)
    assert abs(k["pm_high_gap_pct"]["value"] - 80.0) < TOL  # solo r1
    assert k["gappers_count_pm"]["value"] == 1.0
    assert k["gappers_count"]["value"] == 2.0


# ── Ventanas de Fade (patch §04) ─────────────────────────────────────────────

def test_fade_windows_example():
    r = _example_record()
    merge_derived([r], {("WXYZ", "2026-06-03"): _derived_row()})
    fw = compute_fade_windows([r])

    by_franja = {row["franja"]: row for row in fw["rth"]}
    assert list(by_franja.keys()) == ["09:30", "10:00", "10:30", "11:00"]
    # entrada = close de la vela de la franja; salida = close_1559 = 9.00
    assert abs(by_franja["09:30"]["avg_fade_pct"] - 31.8182) < 1e-2   # (13.2-9)/13.2
    assert abs(by_franja["10:00"]["avg_fade_pct"] - 27.4194) < 1e-2   # (12.4-9)/12.4
    assert abs(by_franja["10:30"]["avg_fade_pct"] - 23.7288) < 1e-2   # (11.8-9)/11.8
    assert abs(by_franja["11:00"]["avg_fade_pct"] - 18.1818) < 1e-2   # (11.0-9)/11.0
    for row in fw["rth"]:
        assert row["pct_favorable"] == 100.0
        assert row["n"] == 1
        assert not row.get("pending_backfill")

    # PM: entrada = PM High, salida = close EOD, universo completo
    assert abs(fw["pm"]["avg_fade_pct"] - 50.0) < TOL                 # (18-9)/18
    assert fw["pm"]["pct_favorable"] == 100.0
    assert fw["pm"]["n"] == 1


def test_fade_windows_pending_backfill_sin_derivado():
    # Sin merge_derived: m0/m90 no existen en la fila → esas franjas quedan
    # pending_backfill (no un 0 falso); m30/m60 siguen calculando.
    fw = compute_fade_windows([_example_record()])
    by_franja = {row["franja"]: row for row in fw["rth"]}
    assert by_franja["09:30"]["pending_backfill"] is True
    assert by_franja["09:30"]["avg_fade_pct"] is None
    assert by_franja["11:00"]["pending_backfill"] is True
    assert abs(by_franja["10:00"]["avg_fade_pct"] - 27.4194) < 1e-2
    assert abs(by_franja["10:30"]["avg_fade_pct"] - 23.7288) < 1e-2


def test_fade_windows_entrada_no_positiva_excluye():
    r = _example_record()
    r["m30_return_pct"] = -100.0   # entrada = 0 → excluido de la franja 10:00
    fw = compute_fade_windows([r])
    by_franja = {row["franja"]: row for row in fw["rth"]}
    assert by_franja["10:00"]["n"] == 0
    assert by_franja["10:00"]["avg_fade_pct"] is None
    assert by_franja["10:30"]["n"] == 1


def test_fade_windows_pct_favorable():
    up, down = _example_record(), _example_record()
    down["close_1559"] = 13.0      # cierra por encima de la entrada de 10:00 (12.40) → desfavorable
    fw = compute_fade_windows([up, down])
    by_franja = {row["franja"]: row for row in fw["rth"]}
    assert by_franja["10:00"]["n"] == 2
    assert abs(by_franja["10:00"]["pct_favorable"] - 50.0) < TOL


# ── Filtros de calidad (patch §01) ───────────────────────────────────────────

def test_quality_reverse_split_5d_excluye():
    # Reverse split (10→1) ejecutado 2 días antes del gap → fuera del universo
    splits = [{"ticker": "WXYZ", "execution_date": "2026-06-01", "split_from": 10, "split_to": 1}]
    kept, q = apply_quality_filters([_example_record()], splits=splits)
    assert kept == []
    assert q["excluded_reverse_split"] == 1


def test_quality_reverse_split_borde_5d_se_mantiene():
    # Ventana (d−5, d]: ejecución exactamente en d−5 (29-may para gap 03-jun) NO excluye
    splits = [{"ticker": "WXYZ", "execution_date": "2026-05-29", "split_from": 10, "split_to": 1}]
    kept, q = apply_quality_filters([_example_record()], splits=splits)
    assert len(kept) == 1
    assert q["excluded_reverse_split"] == 0


def test_quality_reverse_split_futuro_no_excluye():
    # La API devuelve splits anunciados a futuro: no contaminan días anteriores
    splits = [{"ticker": "WXYZ", "execution_date": "2026-06-10", "split_from": 10, "split_to": 1}]
    kept, _ = apply_quality_filters([_example_record()], splits=splits)
    assert len(kept) == 1


def test_quality_forward_split_5d_no_excluye_pero_same_day_si():
    forward_d2 = [{"ticker": "WXYZ", "execution_date": "2026-06-01", "split_from": 1, "split_to": 5}]
    kept, q = apply_quality_filters([_example_record()], splits=forward_d2)
    assert len(kept) == 1          # forward D-2 no es reverse → se queda
    same_day = [{"ticker": "WXYZ", "execution_date": "2026-06-03", "split_from": 1, "split_to": 5}]
    kept, q = apply_quality_filters([_example_record()], splits=same_day)
    assert kept == []              # cualquier split el MISMO día → fuera (paridad cold path)
    assert q["excluded_same_day_split"] == 1


def test_quality_gap_gt_1000_excluye():
    r = _example_record()
    r["gap_pct"] = 1200.0
    kept, q = apply_quality_filters([r, _example_record()])
    assert len(kept) == 1
    assert q["excluded_gap_gt_1000"] == 1
    # exactamente 1000 se queda (la regla es estrictamente >1000)
    r2 = _example_record()
    r2["gap_pct"] = 1000.0
    kept, _ = apply_quality_filters([r2])
    assert len(kept) == 1


def test_quality_black_swan():
    r = _example_record()
    merge_derived([r], {("WXYZ", "2026-06-03"): {"m0_return_pct": None, "m90_return_pct": None,
                                                 "max_spike_5m_pct": 310.0}})
    kept, q = apply_quality_filters([r], black_swan_available=True)
    assert kept == []              # close 2.00 → high 8.20 en 5min = +310% > 300 → fuera
    assert q["excluded_black_swan"] == 1

    r2 = _example_record()
    merge_derived([r2], {("WXYZ", "2026-06-03"): {"max_spike_5m_pct": 290.0}})
    kept, q = apply_quality_filters([r2], black_swan_available=True)
    assert len(kept) == 1
    assert q["excluded_black_swan"] == 0


def test_quality_black_swan_no_disponible_fail_open():
    # Sin derivado: no se evalúa (None en el contador) y NADA se excluye por spike
    r = _example_record()
    r["max_spike_5m_pct"] = 310.0  # aunque la fila lo traiga, available=False no evalúa
    kept, q = apply_quality_filters([r], black_swan_available=False)
    assert len(kept) == 1
    assert q["excluded_black_swan"] is None


def test_quality_ticker_type_paridad_hot():
    kept, q = apply_quality_filters(
        [_example_record()], valid_tickers={"AAPL"})
    assert kept == []
    assert q["excluded_ticker_type"] == 1
    kept, _ = apply_quality_filters([_example_record()], valid_tickers=None)
    assert len(kept) == 1          # sin tabla de tickers → fail-open


def test_build_split_index_filas_sin_ratio():
    # Tabla antigua sin split_from/split_to: cuenta para same-day, no para reverse
    rev, anyday = build_split_index([{"ticker": "WXYZ", "execution_date": "2026-06-03"}])
    assert "WXYZ" not in rev
    assert len(anyday["WXYZ"]) == 1


# ── Distribuciones (MA-02) ───────────────────────────────────────────────────

def test_distributions_example():
    payload = compute_market_analysis([_example_record()], fade_threshold=30.0)
    d = payload["distributions"]
    assert d["hod_time"] == {"09:30-10:00": 100.0}
    assert d["lod_time"] == {"15:00-15:30": 100.0}
    assert d["pmh_time"] == {"07:00-07:30": 100.0}


def test_distributions_ignore_missing_times():
    r = _example_record()
    r["hod_time"] = "--"  # sin tiempo válido → no cuenta en hod_time
    d = compute_market_analysis([r], fade_threshold=30.0)["distributions"]
    assert d["hod_time"] == {}
    assert d["lod_time"] == {"15:00-15:30": 100.0}


# ── records para contexto Edgie (la UI ya no pinta tabla, §05) ───────────────

def test_records_mapping():
    rows = map_recent_gaps([_example_record()])
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "WXYZ"
    assert row["date"] == "2026-06-03"
    assert abs(row["open"] - 13.0) < TOL          # open = rth_open (09:30 estricto)
    assert abs(row["hod"] - 14.0) < TOL
    assert abs(row["pmh"] - 18.0) < TOL
    assert row["close_red"] is True
    assert abs(row["vol_rth"] - 8_200_000.0) < TOL


# ── Robustez ─────────────────────────────────────────────────────────────────

def test_empty_input_is_wellformed():
    payload = compute_market_analysis([], fade_threshold=50.0)
    assert payload["records"] == []
    assert payload["kpis"]["gappers_count"]["value"] == 0.0
    assert payload["kpis"]["gappers_count_pm"]["value"] == 0.0
    assert payload["kpis"]["avg_gap_pct"]["value"] is None
    assert payload["distributions"]["hod_time"] == {}
    fw = payload["fade_windows"]
    assert [row["franja"] for row in fw["rth"]] == ["09:30", "10:00", "10:30", "11:00"]
    for row in fw["rth"]:
        assert row["n"] == 0 and row["avg_fade_pct"] is None
    assert fw["pm"]["n"] == 0 and fw["pm"]["avg_fade_pct"] is None


def test_quality_filters_empty_inputs():
    kept, q = apply_quality_filters([])
    assert kept == [] and q["excluded_reverse_split"] == 0
    kept, q = apply_quality_filters([_example_record()], splits=None)
    assert len(kept) == 1
