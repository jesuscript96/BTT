"""
F0 · Market Analysis — tests de la matemática (Python puro, SIN BD).

Los ejemplos numéricos del PRD (docs/market-analysis/PRD.md §5) se convierten aquí en
asserts. No requieren MotherDuck/GCS: prueban services/market_analysis_service.py sobre
records sintéticos con las claves literales de daily_metrics.

Ejecutar:  cd backend && python -m pytest tests/test_market_analysis.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.market_analysis_service import (  # noqa: E402
    compute_kpis,
    compute_mae_mfe,
    compute_market_analysis,
    map_recent_gaps,
    _quantile,
    _bucket,
    _franja_label,
)

TOL = 1e-3


def _example_record():
    """Fila base del PRD §5:
    prev_close=10, rth_open=13, pm_high=18, rth_high=14, rth_low=8.5,
    pm_low=11.5, close_1559=9, gap_pct=30, day_return=(9-13)/13=-30.77 → red.
    """
    return {
        "ticker": "WXYZ", "timestamp": "2026-06-03",
        "gap_pct": 30.0, "pm_high": 18.0, "pm_low": 11.5, "pm_high_time": "07:15",
        "hod_time": "09:42", "lod_time": "15:10",
        "rth_open": 13.0, "rth_high": 14.0, "rth_low": 8.5,
        "rth_volume": 8_200_000.0, "pm_volume": 1_500_000.0,
        "close_1559": 9.0, "day_return_pct": -30.769, "prev_close": 10.0,
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


# ── KPIs (MA-01) ─────────────────────────────────────────────────────────────

def test_kpis_example():
    k = compute_kpis([_example_record()], fade_threshold=30.0)
    assert k["gappers_count"]["value"] == 1.0
    assert abs(k["avg_gap_pct"]["value"] - 30.0) < TOL
    assert abs(k["pm_high_average"]["value"] - 18.0) < TOL
    assert abs(k["close_red_pct"]["value"] - 100.0) < TOL
    # Fade a EOD = (18-9)/18 = 50%
    assert abs(k["avg_fade_from_pmh"]["value"] - 50.0) < TOL
    assert abs(k["max_fade_from_pmh"]["value"] - 50.0) < TOL
    assert k["max_fade_from_pmh"]["ticker"] == "WXYZ"
    assert k["max_fade_from_pmh"]["date"] == "2026-06-03"
    # Close<VWAP diferido a Fase 2
    assert k["close_lt_vwap_pct"]["value"] is None


def test_kpis_fade_threshold_excludes_below():
    # gap=30 < umbral default 50 ⇒ subuniverso de fade vacío
    k = compute_kpis([_example_record()], fade_threshold=50.0)
    assert k["avg_fade_from_pmh"]["value"] is None
    assert k["max_fade_from_pmh"]["value"] is None


def test_kpis_pm_high_average_excludes_zero():
    r1 = _example_record()
    r2 = _example_record()
    r2["pm_high"] = 0.0  # sin datos PM → excluido del promedio de pm_high
    k = compute_kpis([r1, r2], fade_threshold=30.0)
    assert abs(k["pm_high_average"]["value"] - 18.0) < TOL  # solo r1


# ── MAE/MFE (MA-05) ──────────────────────────────────────────────────────────

def test_mae_mfe_example():
    mm = compute_mae_mfe([_example_record()])
    # RTH MAE = (14-13)/13 = 7.69% → bucket 5-10
    assert mm["rth"]["mae"]["buckets"]["5-10"] == 100.0
    assert abs(mm["rth"]["mae"]["mean"] - 7.6923) < 1e-2
    # RTH MFE = (13-8.5)/13 = 34.6% → bucket 30-50
    assert mm["rth"]["mfe"]["buckets"]["30-50"] == 100.0
    # PM MAE = (18-10)/10 = 80% → bucket >50
    assert mm["pm"]["mae"]["buckets"][">50"] == 100.0
    # PM MFE = (10-11.5)/10 = -15 → clamp 0 → bucket 0-5
    assert mm["pm"]["mfe"]["buckets"]["0-5"] == 100.0
    assert mm["pm"]["mfe"]["mean"] == 0.0


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


# ── Recent Gaps Up (MA-06) ───────────────────────────────────────────────────

def test_recent_gaps_mapping():
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
    assert payload["kpis"]["avg_gap_pct"]["value"] is None
    # mae_mfe siempre bien formado (todos los buckets a 0)
    assert payload["mae_mfe"]["rth"]["mae"]["buckets"]["0-5"] == 0.0
    assert payload["distributions"]["hod_time"] == {}
