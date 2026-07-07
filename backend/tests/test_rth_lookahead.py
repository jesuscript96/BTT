"""Regresión: RTH Open/High/Low deben ser CAUSALES (sin lookahead intradía).

Mismo defecto que tenía Pre-Market High (fix db2bbd0): la constante del día
completo hacía que a las 10:00 una condición "viera" el máximo de las 15:30.
Ahora: cummax/cummin acumulado dentro de la sesión regular, NaN antes de las
09:30, y en after-hours el valor final (ya causal). Cubre motor clásico y
espejo nativo N2a.
"""
import numpy as np
import pandas as pd

from app.services.indicators import compute_indicator
from app.services.strategy_engine import (
    compile_strategy_def,
    translate_strategy,
    translate_strategy_native,
)


def _make_day(peak_minute=870):
    """Día 04:00-19:59: sube linealmente hasta el pico (14:30 por defecto,
    dentro de RTH) y baja después. El máximo RTH NO se conoce hasta las 14:30."""
    ts = pd.date_range("2024-11-12 04:00", "2024-11-12 19:59", freq="1min")
    minutes = ts.hour * 60 + ts.minute
    price = np.where(minutes <= peak_minute,
                     5.0 + 5.0 * (minutes - 240) / (peak_minute - 240),
                     10.0 - 3.0 * (minutes - peak_minute) / (1199 - peak_minute))
    return pd.DataFrame({
        "timestamp": ts, "open": price, "high": price * 1.001,
        "low": price * 0.999, "close": price,
        "volume": np.full(len(ts), 1000),
    }), np.asarray(minutes)


DS = {"rth_open": 6.9, "rth_high": 10.01, "rth_low": 5.0, "prev_close": 5.0}


def test_rth_high_es_causal():
    df, minutes = _make_day()
    serie = np.asarray(compute_indicator("RTH High", df, daily_stats=DS), dtype=np.float64)
    rth = (minutes >= 570) & (minutes < 960)
    # Antes de la primera barra RTH: NaN (el nivel no existe todavía)
    assert np.isnan(serie[minutes < 570]).all(), "RTH High debe ser NaN en premarket"
    # Dentro de RTH: exactamente el máximo acumulado hasta la barra actual
    esperado = np.fmax.accumulate(np.where(rth, df["high"].values, np.nan))
    assert np.allclose(serie[minutes >= 570], esperado[minutes >= 570], equal_nan=True)
    # En after-hours: se mantiene el máximo RTH final (causal: la sesión ya cerró)
    rth_max = df["high"].values[rth].max()
    assert np.allclose(serie[minutes >= 960], rth_max)
    # Y el valor a mitad de sesión NO es el máximo final (eso era el lookahead)
    idx_11h = np.flatnonzero(minutes == 660)[0]
    assert serie[idx_11h] < rth_max, "a las 11:00 no puede conocerse el máximo de las 14:30"


def test_rth_low_es_causal():
    df, minutes = _make_day()
    serie = np.asarray(compute_indicator("RTH Low", df, daily_stats=DS), dtype=np.float64)
    rth = (minutes >= 570) & (minutes < 960)
    assert np.isnan(serie[minutes < 570]).all()
    esperado = np.fmin.accumulate(np.where(rth, df["low"].values, np.nan))
    assert np.allclose(serie[minutes >= 570], esperado[minutes >= 570], equal_nan=True)


def test_rth_open_es_causal():
    df, minutes = _make_day()
    serie = np.asarray(compute_indicator("RTH Open", df, daily_stats=DS), dtype=np.float64)
    assert np.isnan(serie[minutes < 570]).all(), "RTH Open no existe antes de las 09:30"
    first_rth_open = float(df["open"].values[np.argmax(minutes >= 570)])
    assert np.allclose(serie[minutes >= 570], first_rth_open)


def test_frame_solo_premarket_es_nan():
    """Sin barras RTH y sesión regular aún futura: la constante de ds sería
    lookahead → NaN."""
    df, _ = _make_day()
    ts = pd.to_datetime(df["timestamp"])
    df_pm = df[(ts.dt.hour * 60 + ts.dt.minute) < 570].reset_index(drop=True)
    for name in ("RTH Open", "RTH High", "RTH Low"):
        serie = np.asarray(compute_indicator(name, df_pm, daily_stats=DS), dtype=np.float64)
        assert np.isnan(serie).all(), f"{name} en frame solo-premarket debe ser NaN"


def test_frame_solo_afterhours_usa_constante():
    """Sin barras RTH pero la sesión ya pasó: la constante del día es causal."""
    df, _ = _make_day()
    ts = pd.to_datetime(df["timestamp"])
    df_ah = df[(ts.dt.hour * 60 + ts.dt.minute) >= 960].reset_index(drop=True)
    serie = np.asarray(compute_indicator("RTH High", df_ah, daily_stats=DS), dtype=np.float64)
    assert np.allclose(serie, DS["rth_high"])


def test_estrategia_breakout_rth_sin_lookahead():
    """'Close CROSSES_ABOVE RTH High' con la constante antigua casi nunca
    disparaba (el techo era el máximo final) o disparaba mal; con la serie
    causal dispara en cada nuevo máximo. Verifica además paridad legacy↔nativo."""
    df, minutes = _make_day()
    strategy = {
        "bias": "long",
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {"operator": "AND", "conditions": [{
                "type": "indicator_comparison",
                "source": {"name": "High"}, "comparator": "GREATER_THAN",
                "target": {"name": "RTH High"},
            }]},
        },
        "exit_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": []}},
        "risk_management": {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 10}},
    }
    compiled = compile_strategy_def(strategy)
    assert not compiled["_indicator_plan"]["has_special"]

    legacy = translate_strategy(df.copy(), strategy, DS, compiled=compiled)
    leg_entries = np.asarray(legacy["entries"], dtype=bool)
    assert not leg_entries[minutes < 570].any(), "no puede romper el RTH High antes de RTH"

    ts = pd.to_datetime(df["timestamp"])
    ts_int64 = ts.values.astype("datetime64[ns]").astype(np.int64)
    abs_min = ts_int64 // 60_000_000_000
    arrays = {
        "open": np.asarray(df["open"], dtype=np.float64),
        "high": np.asarray(df["high"], dtype=np.float64),
        "low": np.asarray(df["low"], dtype=np.float64),
        "close": np.asarray(df["close"], dtype=np.float64),
        "volume": np.asarray(df["volume"], dtype=np.float64),
        "minutes_arr": abs_min % 1440, "abs_min_arr": abs_min,
    }
    native = translate_strategy_native(arrays, compiled, DS)
    assert np.array_equal(leg_entries, np.asarray(native["entries"], dtype=bool)), \
        "paridad legacy↔nativo rota en RTH High causal"
