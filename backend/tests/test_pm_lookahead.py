"""
Regresión anti-lookahead de niveles premarket (2026-07-06).

Bug original: "PM High Gap (%)", "Pre-Market High" y "Pre-Market Low" devolvían
el valor FINAL del premarket como constante de todo el día → una condición tipo
"PM High Gap >= 50%" evaluaba True a las 07:00 con un máximo que el ticker no
hizo hasta las 09:00 (entradas antes de que exista el gap). Los arrays
pm_high/pm_low que anclan stops de estructura (PMH/PML) tenían el mismo defecto.

Contrato: los niveles PM son ACUMULADOS hasta la barra actual (causales); tras
las 09:30 valen el PM completo (comportamiento RTH intacto).
"""
import numpy as np
import pandas as pd

from app.services.strategy_engine import translate_strategy
from app.services.indicators import _pm_running_series


def _mk_day(prev_close=1.0):
    """04:00→11:00. Plano en 1.00 hasta las 08:00; rampa hasta 1.60 a las 09:00.

    Con prev_close=1.0, el PM High Gap >= 50% solo es cierto (causalmente) a
    partir de la primera barra cuyo high acumulado alcanza 1.50.
    """
    n = 420
    ts = pd.date_range("2025-03-05 04:00", periods=n, freq="1min")
    high = np.full(n, 1.001)
    # rampa 08:00 (idx 240) → 09:00 (idx 300): 1.00 → 1.60 lineal
    ramp = np.linspace(1.0, 1.6, 61)
    high[240:301] = ramp
    high[301:] = 1.6
    close = high - 0.001
    open_ = np.roll(close, 1); open_[0] = close[0]
    low = np.minimum(open_, close) - 0.001
    df = pd.DataFrame({
        "ticker": "TST", "timestamp": ts,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": np.full(n, 10_000),
        "hod": np.maximum.accumulate(high),
        "lod": np.minimum.accumulate(low),
        # columnas de estructura que translate_strategy espera en el mini_df
        "pm_high": np.fmax.accumulate(np.where(np.arange(n) < 330, high, np.nan)),
        "pm_low": np.fmin.accumulate(np.where(np.arange(n) < 330, low, np.nan)),
        "prev_high": np.roll(np.maximum.accumulate(high), 1),
        "prev_low": np.roll(np.minimum.accumulate(low), 1),
        "prev_close": np.full(n, prev_close),
        "yesterday_open": np.full(n, prev_close),
    })
    return df


STRATEGY = {
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "PM High Gap (%)"}, "comparator": "GREATER_THAN_OR_EQUAL",
         "target": 50},
    ]}},
    "risk_management": {"use_hard_stop": True,
                        "hard_stop": {"type": "Percentage", "value": 30}},
}


def test_pm_high_gap_es_causal():
    df = _mk_day(prev_close=1.0)
    sigs = translate_strategy(df, STRATEGY, daily_stats={"prev_close": 1.0, "pm_high": 1.6})
    entries = np.asarray(sigs["entries"])

    # primera barra cuyo high acumulado alcanza 1.50 (gap 50% real)
    first_valid = int(np.argmax(np.maximum.accumulate(df["high"].values) >= 1.5))
    assert entries.any(), "la condición debe disparar cuando el gap existe"
    first_entry = int(np.argmax(entries))
    assert first_entry >= first_valid, (
        f"LOOKAHEAD: entrada en barra {first_entry} (min {240 + first_entry - 240}) "
        f"antes de que el PMH acumulado alcance el 50% (barra {first_valid})"
    )


def test_pm_running_series_contrato():
    df = _mk_day()
    run_h = _pm_running_series(df, df.index, "high").values
    run_l = _pm_running_series(df, df.index, "low").values

    ts = pd.to_datetime(df["timestamp"])
    minutes = ts.dt.hour.values * 60 + ts.dt.minute.values
    pm = (minutes >= 240) & (minutes < 570)

    # causal: en cada barra PM, el running == max/min de las barras PM <= actual
    for i in (0, 100, 250, 299):
        assert run_h[i] == df["high"].values[: i + 1][pm[: i + 1]].max()
        assert run_l[i] == df["low"].values[: i + 1][pm[: i + 1]].min()
    # tras el PM (>=09:30) se mantiene el PM completo → RTH sin cambios
    post = np.where(~pm & (minutes >= 570))[0]
    assert np.all(run_h[post] == df["high"].values[pm].max())
    assert np.all(run_l[post] == df["low"].values[pm].min())


def test_pre_market_high_indicador_causal():
    df = _mk_day()
    strat = {
        "bias": "short", "apply_day": "gap_day",
        "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
            {"type": "indicator_comparison", "timeframe": "1m",
             "source": {"name": "PM High"}, "comparator": "GREATER_THAN_OR_EQUAL",
             "target": 1.5},
        ]}},
        "risk_management": {"use_hard_stop": True,
                            "hard_stop": {"type": "Percentage", "value": 30}},
    }
    # ds trae el PMH final (1.6): NO debe usarse como constante para todo el día
    sigs = translate_strategy(df, strat, daily_stats={"prev_close": 1.0, "pm_high": 1.6})
    entries = np.asarray(sigs["entries"])
    first_valid = int(np.argmax(np.maximum.accumulate(df["high"].values) >= 1.5))
    assert entries.any()
    assert int(np.argmax(entries)) >= first_valid
