"""
Semántica de "Current Gap (%)" (feature Álvaro, 2026-08-18):

    Current_Gap[t] = (close[t] − prev_close) / prev_close × 100

- prev_close usa la MISMA cadena de fallback que "PM High Gap (%)"
  (previous_close → prev_close → lag_rth_close_1 → close de la 1ª barra).
- A diferencia de "PM High Gap (%)" (máximo acumulado del premarket, que se
  congela al cerrar el PM), Current Gap sigue al precio vela a vela durante
  TODO el día (PM y RTH): si el precio cae, el gap cae.
- Comparadores de estado (>=, <=, >, <): la condición debe cumplirse en la
  vela que dispara la entrada (el fill es en la apertura de la siguiente por
  look-ahead prevention, igual que el resto de condiciones).

Cubre: paridad legacy↔nativa (1m y 5m), contrato de producto frente a
PM High Gap, y fallbacks de prev_close.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import numpy as np
import pandas as pd

from test_n2a_native_equivalence import (_strategy, _cmp, _make_day_df,
                                         _make_daily_stats, _make_arrays)
from app.services.strategy_engine import (compile_strategy_def, translate_strategy,
                                          translate_strategy_native)


def _signals(strategy_def, df, ds):
    compiled = compile_strategy_def(strategy_def)
    assert not compiled.get("_indicator_plan", {}).get("has_special"), \
        "estas estrategias deben ser nativas-elegibles"
    legacy = translate_strategy(df.copy(), strategy_def, ds, compiled=compiled)
    native = translate_strategy_native(_make_arrays(df), compiled, ds)
    l = np.asarray(legacy["entries"], dtype=bool)
    n = np.asarray(native["entries"], dtype=bool)
    assert (l == n).all(), "legacy y nativo divergen"
    return l


def _deterministic_day_df(closes):
    """Día 1m sin huecos con closes controlados; high=close+0.1, low=close-0.1."""
    ts = pd.date_range("2024-11-12 08:00", periods=len(closes), freq="1min")
    c = np.asarray(closes, dtype=np.float64)
    return pd.DataFrame({
        "timestamp": ts,
        "open": c, "high": c + 0.1, "low": c - 0.1,
        "close": c, "volume": np.full(len(c), 1000.0),
    })


def test_current_gap_paridad_1m():
    df = _make_day_df(seed=21, date="2024-11-12")
    ds = _make_daily_stats(df)
    sig = _signals(_strategy([_cmp({"name": "Current Gap (%)"}, "GREATER_THAN_OR_EQUAL", 2.5)]), df, ds)
    expected = (np.asarray(df["close"], dtype=np.float64) - 9.5) / 9.5 * 100.0 >= 2.5
    assert (sig == expected).all(), "Current Gap debe ser (close-prev_close)/prev_close*100 por barra"


def test_current_gap_paridad_5m():
    df = _make_day_df(seed=22, date="2024-11-12")
    ds = _make_daily_stats(df)
    _signals(_strategy([_cmp({"name": "Current Gap (%)"}, "LESS_THAN_OR_EQUAL", 10, tf="5m")]), df, ds)


def test_current_gap_sigue_al_precio_pm_high_gap_se_congela():
    """Contrato de producto: el PM hace +6%, luego el precio cae a +3%.
    PM High Gap >= 5 sigue True (el máximo no baja); Current Gap >= 5 ya no."""
    n_pm, n_fall = 21, 40
    closes = np.concatenate([
        np.full(n_pm, 106.0),   # 08:00-08:20: precio a +6% sobre prev_close=100
        np.full(n_fall, 103.0), # 08:21-...:  precio cae a +3%
    ])
    df = _deterministic_day_df(closes)
    ds = {"previous_close": 100.0, "prev_close": 100.0, "pm_high": 106.1}

    pmh = _signals(_strategy([_cmp({"name": "PM High Gap (%)"}, "GREATER_THAN_OR_EQUAL", 5)]), df, ds)
    cur = _signals(_strategy([_cmp({"name": "Current Gap (%)"}, "GREATER_THAN_OR_EQUAL", 5)]), df, ds)

    assert pmh[:n_pm].all() and pmh[n_pm:].all(), "PM High Gap se queda en el máximo (carraca)"
    assert cur[:n_pm].all(), "Current Gap cumple mientras el precio está a +6%"
    assert not cur[n_pm:].any(), "Current Gap debe dejar de cumplirse cuando el precio cae a +3%"
    assert (cur == ((closes - 100.0) / 100.0 * 100.0 >= 5)).all()


def test_current_gap_fallback_prev_close():
    """Sin claves de cierre de ayer en daily_stats, cae al close de la 1ª barra
    (misma cadena de fallback que PM High Gap). Con prev_close=0 → NaN → False."""
    closes = np.array([100.0, 101.0, 99.0, 105.0])
    df = _deterministic_day_df(closes)

    ds_no_key = {}
    sig = _signals(_strategy([_cmp({"name": "Current Gap (%)"}, "GREATER_THAN_OR_EQUAL", 0)]), df, ds_no_key)
    assert (sig == ((closes - 100.0) / 100.0 * 100.0 >= 0)).all(), "fallback: close[0] como referencia"

    ds_zero = {"previous_close": 0.0}
    sig0 = _signals(_strategy([_cmp({"name": "Current Gap (%)"}, "GREATER_THAN_OR_EQUAL", -1000)]), df, ds_zero)
    assert not sig0.any(), "prev_close=0 → NaN → toda comparación es False"
