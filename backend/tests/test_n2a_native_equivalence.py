"""Equivalencia N2a: translate_strategy_native vs translate_strategy (la especificación).

Cubre lo que motivó apagar N2a (BTT_N2A_NATIVE_ENABLED=0, 2026-07-04) y los fixes
de fix/n2a-parity (2026-07-06):
  - barrido del catálogo nativo completo (señales idénticas por indicador)
  - timeframes != 1m con resample por reloj + alineación closed-bar (con huecos
    de minutos, como el premarket real) y herencia de tf del padre
  - comparadores CROSSES_ABOVE/BELOW
  - ventanas horarias de entrada
  - PM High/Low/Gap causales (sin lookahead) y fallbacks de daily_stats
  - risk management: ATR Multiplier y partial TPs
  - gate has_special: todo lo NO nativo cae al legacy (nunca 0-trades silencioso)

Datos 100% sintéticos — no toca DuckDB/GCS.
"""
import numpy as np
import pandas as pd
import pytest

from app.services.strategy_engine import (
    compile_strategy_def,
    translate_strategy,
    translate_strategy_native,
    _RAW_INDICATOR_DISPATCH,
)


# ─── Datos sintéticos ─────────────────────────────────────────────────────

def _make_day_df(seed=7, start="04:00", end="15:59", date="2024-11-12",
                 with_gaps=True):
    """Día 1m con huecos de minutos (premarket ilíquido realista)."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(f"{date} {start}", f"{date} {end}", freq="1min")
    if with_gaps:
        minutes = ts.hour * 60 + ts.minute
        keep = np.ones(len(ts), dtype=bool)
        keep &= ~((minutes % 7) == 3)              # huecos dispersos
        keep &= ~((minutes >= 575) & (minutes < 580))   # bucket 5m entero (09:35-09:39)
        keep &= ~((minutes >= 257) & (minutes < 300))   # tramo PM ilíquido
        ts = ts[keep]
    n = len(ts)
    close = 10.0 + np.cumsum(rng.normal(0, 0.05, n))
    close = np.maximum(close, 1.0)
    spread = np.abs(rng.normal(0, 0.03, n))
    open_ = close + rng.normal(0, 0.02, n)
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.integers(100, 50_000, n).astype(np.int64)
    return pd.DataFrame({
        "timestamp": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


def _make_two_day_df(seed=11):
    """Frame multi-día (modo swing): el bucketing por minutos-del-día colisiona
    entre días si no se usan minutos absolutos."""
    d1 = _make_day_df(seed=seed, date="2024-11-11")
    d2 = _make_day_df(seed=seed + 1, date="2024-11-12")
    return pd.concat([d1, d2], ignore_index=True)


def _make_daily_stats(df):
    ts = pd.to_datetime(df["timestamp"])
    minutes = ts.dt.hour * 60 + ts.dt.minute
    pm = df[(minutes >= 240) & (minutes < 570)]
    rth = df[(minutes >= 570) & (minutes < 960)]
    return {
        "prev_close": 9.5, "previous_close": 9.5,
        "yesterday_open": 9.2, "yesterday_high": 10.1, "yesterday_low": 9.0,
        "yesterday_close": 9.5, "lag_rth_close_1": 9.5,
        "pm_high": float(pm["high"].max()) if len(pm) else np.nan,
        "pm_low": float(pm["low"].min()) if len(pm) else np.nan,
        "rth_open": float(rth["open"].iloc[0]) if len(rth) else np.nan,
        "rth_high": float(rth["high"].max()) if len(rth) else np.nan,
        "rth_low": float(rth["low"].min()) if len(rth) else np.nan,
        "gap_pct": 5.0,
    }


def _make_arrays(df):
    """Réplica exacta de la construcción de arrays_native en
    backtest_signals._compute_signals_for_pair."""
    ts = pd.to_datetime(df["timestamp"])
    ts_int64 = ts.values.astype("datetime64[ns]").astype(np.int64)
    abs_min = ts_int64 // 60_000_000_000
    return {
        "open": np.asarray(df["open"], dtype=np.float64),
        "high": np.asarray(df["high"], dtype=np.float64),
        "low": np.asarray(df["low"], dtype=np.float64),
        "close": np.asarray(df["close"], dtype=np.float64),
        "volume": np.asarray(df["volume"], dtype=np.float64),
        "minutes_arr": abs_min % 1440,
        "abs_min_arr": abs_min,
    }


# ─── Constructores de estrategias ─────────────────────────────────────────

def _strategy(entry_conds, operator="AND", tf="1m", bias="long", risk=None,
              time_windows=None, exit_conds=None, exit_tf=None):
    return {
        "bias": bias,
        "entry_logic": {
            "timeframe": tf,
            "root_condition": {"operator": operator, "conditions": entry_conds},
            "entry_time_windows": time_windows or [],
        },
        "exit_logic": {
            "timeframe": exit_tf or tf,
            "root_condition": {
                "operator": "AND",
                "conditions": exit_conds or [_cmp({"name": "Close"}, "LESS_THAN",
                                                  {"name": "VWAP"})],
            },
        },
        "risk_management": risk or {
            "use_hard_stop": True,
            "hard_stop": {"type": "Percentage", "value": 5},
        },
    }


def _cmp(source, comparator, target, tf=None):
    cond = {"type": "indicator_comparison", "source": source,
            "comparator": comparator, "target": target}
    if tf is not None:
        cond["timeframe"] = tf
    return cond


# ─── Harness de comparación ───────────────────────────────────────────────

def _assert_equivalent(strategy_def, df, daily_stats, expect_native=True):
    compiled = compile_strategy_def(strategy_def)
    plan = compiled.get("_indicator_plan", {})
    if expect_native:
        assert not plan.get("has_special"), (
            "la estrategia debería ser nativa-elegible y el gate la mandó a legacy"
        )
    legacy = translate_strategy(df.copy(), strategy_def, daily_stats, compiled=compiled)
    native = translate_strategy_native(_make_arrays(df), compiled, daily_stats)

    leg_entries = np.asarray(legacy["entries"], dtype=bool)
    leg_exits = np.asarray(legacy["exits"], dtype=bool)
    nat_entries = np.asarray(native["entries"], dtype=bool)
    nat_exits = np.asarray(native["exits"], dtype=bool)

    assert np.array_equal(leg_entries, nat_entries), (
        f"entries divergen: legacy={leg_entries.sum()} native={nat_entries.sum()} "
        f"primeras diffs={np.flatnonzero(leg_entries != nat_entries)[:10]}"
    )
    assert np.array_equal(leg_exits, nat_exits), (
        f"exits divergen: legacy={leg_exits.sum()} native={nat_exits.sum()}"
    )

    for key in ("direction", "sl_trail", "accept_reentries", "max_reentries",
                "tp_time_limit", "trail_pct", "partial_take_profits"):
        assert legacy.get(key) == native.get(key), (
            f"{key}: legacy={legacy.get(key)!r} native={native.get(key)!r}"
        )
    for key in ("sl_stop", "tp_stop"):
        lv, nv = legacy.get(key), native.get(key)
        if lv is None or nv is None:
            assert lv is None and nv is None, f"{key}: legacy={lv!r} native={nv!r}"
        elif isinstance(lv, float) and np.isnan(lv):
            assert isinstance(nv, float) and np.isnan(nv), f"{key}: {lv!r} vs {nv!r}"
        else:
            assert lv == nv, f"{key}: legacy={lv!r} native={nv!r}"
    return leg_entries


def _median_target(df, daily_stats, cfg):
    """Target = mediana de la serie legacy (señales mixtas, no triviales)."""
    from app.services.strategy_engine import _compute_from_config
    series = _compute_from_config(dict(cfg), df.copy(), daily_stats, cache=None)
    med = np.nanmedian(np.asarray(series, dtype=np.float64))
    return 0.0 if np.isnan(med) else float(med)


# ─── 1. Barrido del catálogo nativo (1m) ──────────────────────────────────

_CATALOG = [
    {"name": "Close"}, {"name": "Open"}, {"name": "High"}, {"name": "Low"},
    {"name": "Bar Close"}, {"name": "Bar Open"}, {"name": "Volume"},
    {"name": "SMA", "period": 20}, {"name": "EMA", "period": 20},
    {"name": "VWAP"}, {"name": "AVWAP"},
    {"name": "RSI", "period": 14}, {"name": "ATR", "period": 14},
    {"name": "CCI", "period": 20}, {"name": "ROC", "period": 12},
    {"name": "Momentum", "period": 10},
    {"name": "MACD", "period": 12, "period2": 26, "period3": 9},
    {"name": "MACD Signal", "period": 12, "period2": 26, "period3": 9},
    {"name": "MACD Histogram", "period": 12, "period2": 26, "period3": 9},
    {"name": "Stochastic", "period": 14, "period2": 3},
    {"name": "Stochastic %D", "period": 14, "period2": 3},
    {"name": "DMI", "period": 14}, {"name": "DMI-", "period": 14},
    {"name": "Bollinger Bands", "period": 20, "stdDev": 2},
    {"name": "Bollinger Upper", "period": 20, "stdDev": 2},
    {"name": "Bollinger Middle", "period": 20, "stdDev": 2},
    {"name": "Bollinger Lower", "period": 20, "stdDev": 2},
    {"name": "OBV"},
    {"name": "Heikin-Ashi"}, {"name": "HA Close"}, {"name": "HA Open"},
    {"name": "HA High"}, {"name": "HA Low"},
    {"name": "Consecutive Red Candles"}, {"name": "Consecutive Green Candles"},
    {"name": "Consecutive Higher Highs"}, {"name": "Consecutive Lower Highs"},
    {"name": "Consecutive Lower Lows"}, {"name": "Consecutive Higher Lows"},
    {"name": "Linear Regression", "period": 14},
    {"name": "Yesterday Open"}, {"name": "Yesterday Close"},
    {"name": "Previous Close"}, {"name": "Yesterday High"}, {"name": "Yesterday Low"},
    {"name": "Day Open"}, {"name": "Current Open"},
    {"name": "Pre-Market High"}, {"name": "Pre-Market Low"},
    {"name": "PM High Gap (%)"},
    {"name": "High of Day"}, {"name": "Low of Day"},
    {"name": "Prev. Close Bar"}, {"name": "Prev. Bar Close"},
    {"name": "Prev. Open Bar"}, {"name": "Prev. High Bar"}, {"name": "Prev. Low Bar"},
    {"name": "RTH Open"}, {"name": "RTH High"}, {"name": "RTH Low"},
    {"name": "Pivot Points"}, {"name": "PP"},
    {"name": "R1"}, {"name": "S1"}, {"name": "R2"}, {"name": "S2"},
]


@pytest.mark.parametrize("cfg", _CATALOG, ids=lambda c: c["name"])
def test_catalogo_nativo_1m(cfg):
    df = _make_day_df()
    ds = _make_daily_stats(df)
    target = _median_target(df, ds, cfg)
    strat = _strategy([_cmp(dict(cfg), "GREATER_THAN", target)])
    _assert_equivalent(strat, df, ds)


def test_catalogo_sin_daily_stats():
    """Fallbacks cuando daily_stats viene vacío (Day Open→o[0], RTH desde barras,
    PM causal sin constante)."""
    df = _make_day_df(seed=13)
    for cfg in ({"name": "Day Open"}, {"name": "RTH Open"}, {"name": "RTH High"},
                {"name": "RTH Low"}, {"name": "Pre-Market High"},
                {"name": "Pre-Market Low"}, {"name": "PM High Gap (%)"},
                {"name": "Yesterday Close"}):
        target = _median_target(df, {}, cfg)
        strat = _strategy([_cmp(dict(cfg), "GREATER_THAN_OR_EQUAL", target)])
        _assert_equivalent(strat, df, {})


def test_dia_sin_premarket():
    """Día solo-RTH: PM High cae a la constante de ds en ambos paths."""
    df = _make_day_df(seed=17, start="09:30", end="15:59")
    ds = _make_daily_stats(df)
    ds["pm_high"], ds["pm_low"] = 11.2, 9.8
    for name in ("Pre-Market High", "Pre-Market Low", "PM High Gap (%)"):
        strat = _strategy([_cmp({"name": name}, "LESS_THAN", 10.5)])
        _assert_equivalent(strat, df, ds)


# ─── 2. Timeframes: resample por reloj + closed-bar + herencia ────────────

@pytest.mark.parametrize("tf", ["5m", "15m", "30m", "1h", "1d"])
def test_timeframe_explicito(tf):
    df = _make_day_df(seed=23)
    ds = _make_daily_stats(df)
    strat = _strategy([
        _cmp({"name": "Close"}, "GREATER_THAN", {"name": "SMA", "period": 5}, tf=tf),
    ])
    _assert_equivalent(strat, df, ds)


@pytest.mark.parametrize("tf", ["5m", "15m"])
def test_timeframe_heredado_del_padre(tf):
    """Condición SIN tf propio hereda el del entry_logic (el nativo lo ignoraba
    → lookup fallido → all-False silencioso)."""
    df = _make_day_df(seed=29)
    ds = _make_daily_stats(df)
    strat = _strategy(
        [_cmp({"name": "Close"}, "GREATER_THAN", {"name": "EMA", "period": 4})],
        tf=tf,
    )
    _assert_equivalent(strat, df, ds)


def test_timeframes_mezclados_con_grupo_anidado():
    df = _make_day_df(seed=31)
    ds = _make_daily_stats(df)
    strat = _strategy(
        [
            _cmp({"name": "Close"}, "GREATER_THAN", {"name": "VWAP"}, tf="1m"),
            {
                "type": "group", "operator": "OR",
                "conditions": [
                    _cmp({"name": "RSI", "period": 7}, "LESS_THAN", 65, tf="5m"),
                    _cmp({"name": "Close"}, "GREATER_THAN",
                         {"name": "SMA", "period": 3}, tf="15m"),
                ],
            },
        ],
        operator="AND",
    )
    _assert_equivalent(strat, df, ds)


def test_timeframe_en_indicadores_de_sesion():
    """PM High causal calculado sobre barras resampleadas (timestamp 'first')."""
    df = _make_day_df(seed=37)
    ds = _make_daily_stats(df)
    strat = _strategy(
        [_cmp({"name": "Pre-Market High"}, "GREATER_THAN", 9.0, tf="5m")],
    )
    _assert_equivalent(strat, df, ds)


def test_frame_multidia_swing():
    """Dos días concatenados (swing): el bucketing debe usar minutos ABSOLUTOS."""
    df = _make_two_day_df()
    ds = _make_daily_stats(df)
    strat = _strategy(
        [_cmp({"name": "Close"}, "GREATER_THAN", {"name": "SMA", "period": 6}, tf="5m")],
    )
    _assert_equivalent(strat, df, ds)


def test_timeframe_desconocido_se_trata_como_1m():
    """Paridad con el quirk legacy: tf_map.get(tf_raro, '1min')."""
    df = _make_day_df(seed=41)
    ds = _make_daily_stats(df)
    strat = _strategy([_cmp({"name": "Close"}, "GREATER_THAN",
                            {"name": "VWAP"}, tf="3m")])
    _assert_equivalent(strat, df, ds)


# ─── 3. Comparadores ──────────────────────────────────────────────────────

@pytest.mark.parametrize("comparator", [
    "GREATER_THAN", "LESS_THAN", "GREATER_THAN_OR_EQUAL",
    "LESS_THAN_OR_EQUAL", "EQUAL", "CROSSES_ABOVE", "CROSSES_BELOW",
])
def test_comparadores(comparator):
    df = _make_day_df(seed=43)
    ds = _make_daily_stats(df)
    strat = _strategy([_cmp({"name": "Close"}, comparator, {"name": "VWAP"})])
    _assert_equivalent(strat, df, ds)


def test_crosses_contra_constante():
    df = _make_day_df(seed=47)
    ds = _make_daily_stats(df)
    med = float(np.nanmedian(df["close"]))
    strat = _strategy([_cmp({"name": "Close"}, "CROSSES_ABOVE", med)])
    entries = _assert_equivalent(strat, df, ds)
    assert entries.sum() > 0, "caso trivial: el cruce debería disparar alguna vez"


def test_crosses_en_timeframe_5m():
    df = _make_day_df(seed=53)
    ds = _make_daily_stats(df)
    strat = _strategy([_cmp({"name": "Close"}, "CROSSES_ABOVE",
                            {"name": "SMA", "period": 4}, tf="5m")])
    _assert_equivalent(strat, df, ds)


def test_target_string_numerico():
    df = _make_day_df(seed=59)
    ds = _make_daily_stats(df)
    strat = _strategy([_cmp({"name": "RSI", "period": 14}, "GREATER_THAN", "55")])
    _assert_equivalent(strat, df, ds)


def test_df_minusculo():
    df = _make_day_df(seed=61).head(3)
    ds = _make_daily_stats(df)
    strat = _strategy([_cmp({"name": "Close"}, "CROSSES_ABOVE", {"name": "Open"})])
    _assert_equivalent(strat, df, ds)


# ─── 4. Ventanas horarias ─────────────────────────────────────────────────

def test_ventana_horaria_entrada():
    df = _make_day_df(seed=67)
    ds = _make_daily_stats(df)
    base = _strategy([_cmp({"name": "Close"}, "GREATER_THAN", 0.0)])
    sin_ventana = _assert_equivalent(base, df, ds)

    con_ventana = _strategy(
        [_cmp({"name": "Close"}, "GREATER_THAN", 0.0)],
        time_windows=[{"from_time": "07:00", "to_time": "08:00"}],
    )
    entries = _assert_equivalent(con_ventana, df, ds)
    assert entries.sum() < sin_ventana.sum(), "la ventana debería recortar entradas"
    minutes = _make_arrays(df)["minutes_arr"]
    assert not entries[(minutes < 420) | (minutes > 480)].any(), \
        "entradas fuera de 07:00-08:00"


def test_ventanas_multiples_e_invalidas():
    df = _make_day_df(seed=71)
    ds = _make_daily_stats(df)
    strat = _strategy(
        [_cmp({"name": "Close"}, "GREATER_THAN", 0.0)],
        time_windows=[
            {"from_time": "05:00", "to_time": "05:30"},
            {"from_time": "", "to_time": "10:00"},           # ignorada (legacy: continue)
            {"from_time": "bogus", "to_time": "10:00"},      # error parseo → continue
            {"from_time": "14:00", "to_time": "14:15"},
        ],
    )
    _assert_equivalent(strat, df, ds)


# ─── 5. Risk management ───────────────────────────────────────────────────

def test_atr_multiplier_stop():
    df = _make_day_df(seed=73)
    ds = _make_daily_stats(df)
    strat = _strategy(
        [_cmp({"name": "Close"}, "GREATER_THAN", {"name": "VWAP"})],
        risk={"use_hard_stop": True, "hard_stop": {"type": "ATR Multiplier", "value": 2.5}},
    )
    compiled = compile_strategy_def(strat)
    legacy = translate_strategy(df.copy(), strat, ds, compiled=compiled)
    native = translate_strategy_native(_make_arrays(df), compiled, ds)
    assert legacy["sl_stop"] is not None and native["sl_stop"] is not None
    assert legacy["sl_stop"] == native["sl_stop"], \
        f"ATR sl_stop diverge: {legacy['sl_stop']!r} vs {native['sl_stop']!r}"


def test_partial_take_profits():
    df = _make_day_df(seed=79)
    ds = _make_daily_stats(df)
    strat = _strategy(
        [_cmp({"name": "Close"}, "GREATER_THAN", {"name": "VWAP"})],
        risk={
            "use_hard_stop": True,
            "hard_stop": {"type": "Percentage", "value": 10},
            "take_profit_mode": "Partial",
            "partial_take_profits": [
                {"distance_pct": 5, "capital_pct": 50},
                {"distance_pct": "EOD", "capital_pct": 25},
                {"distance_pct": "HOUR:14:30", "capital_pct": 25},
                {"distance_pct": 0, "capital_pct": 10},   # inválido → fuera
            ],
        },
    )
    _assert_equivalent(strat, df, ds)


@pytest.mark.parametrize("risk", [
    {"use_hard_stop": True, "hard_stop": {"type": "Fixed Amount", "value": 1.5}},
    {"use_hard_stop": True, "hard_stop": {"type": "Market Structure (HOD/LOD)", "value": 0}},
    {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 30},
     "trailing_stop": {"active": True, "type": "Percentage", "buffer_pct": 3}},
    {"use_take_profit": True, "take_profit": {"type": "Percentage", "value": 8}},
    {"use_take_profit": True, "take_profit": {"type": "Hour", "value": "15:00"}},
], ids=["fixed", "hod-lod", "trailing", "tp-pct", "tp-hour"])
def test_risk_variantes(risk):
    df = _make_day_df(seed=83)
    ds = _make_daily_stats(df)
    strat = _strategy([_cmp({"name": "Close"}, "GREATER_THAN", {"name": "VWAP"})],
                      risk=risk)
    _assert_equivalent(strat, df, ds)


# ─── 6. Gate has_special: nada no-nativo pasa en silencio ─────────────────

def _plan_special(strategy_def):
    return compile_strategy_def(strategy_def)["_indicator_plan"]["has_special"]


def test_gate_indicador_no_soportado():
    for name in ("Williams %R", "ADX", "Parabolic SAR", "Donchian Channels",
                 "RVOL", "Time of Day", "Range of time", "Max N Bars",
                 "Accumulated Volume", "Chaikin Money Flow", "WMA",
                 "Yesterday Volume", "Candle Range %", "PM Open", "AM Open",
                 "Previous max", "Previous min", "Ret % PM",
                 "Max of last X days"):
        assert name not in _RAW_INDICATOR_DISPATCH, f"{name} ya es nativo: actualizar test"
        strat = _strategy([_cmp({"name": name, "period": 14}, "GREATER_THAN", 1.0)])
        assert _plan_special(strat), f"{name} debería gatear a legacy"


def test_gate_comparador_no_soportado():
    strat = _strategy([_cmp({"name": "Close"}, "DISTANCE_LESS_THAN", 1.0)])
    assert _plan_special(strat)


def test_gate_cfg_campos_ignorados():
    for extra in ({"band_line": "Lower"}, {"band_line": "Basis"},
                  {"calc_on_heikin": True}, {"offset": 2}):
        cfg = {"name": "Bollinger Bands", "period": 20, "stdDev": 2, **extra}
        strat = _strategy([_cmp(cfg, "GREATER_THAN", 1.0)])
        assert _plan_special(strat), f"cfg con {extra} debería gatear a legacy"
    # band_line Upper/None NO gatea (el nativo devuelve la banda superior igual
    # que el legacy por defecto)
    cfg = {"name": "Bollinger Bands", "period": 20, "stdDev": 2, "band_line": "Upper"}
    assert not _plan_special(_strategy([_cmp(cfg, "GREATER_THAN", 1.0)]))


def test_gate_condiciones_especiales():
    strat_pattern = _strategy([{"type": "candle_pattern", "pattern": "DOJI"}])
    assert _plan_special(strat_pattern)
    strat_dist = _strategy([{
        "type": "price_level_distance", "source": {"name": "Close"},
        "level": {"name": "VWAP"}, "comparator": "DISTANCE_LESS_THAN",
        "value_pct": 1.0,
    }])
    assert _plan_special(strat_dist)


def test_gate_anidado():
    """Un hueco de soporte dentro de un grupo anidado también gatea."""
    strat = _strategy([
        _cmp({"name": "Close"}, "GREATER_THAN", {"name": "VWAP"}),
        {"type": "group", "operator": "OR", "conditions": [
            _cmp({"name": "Williams %R", "period": 14}, "LESS_THAN", -80),
        ]},
    ])
    assert _plan_special(strat)


def test_gate_targets_raros():
    assert _plan_special(_strategy([_cmp({"name": "Close"}, "GREATER_THAN", "no-numerico")]))
    assert _plan_special(_strategy([_cmp({"name": "Close"}, "GREATER_THAN", None)]))
    assert _plan_special(_strategy([_cmp({}, "GREATER_THAN", 1.0)]))
    assert not _plan_special(_strategy([_cmp({"name": "Close"}, "GREATER_THAN", "55")]))


def test_gate_estrategia_real_es_nativa():
    """La estrategia del caso FOXO (short PMH-gap≥50 con ventana 07-08) debe ser
    nativa-elegible tras los fixes — es el objetivo del speedup."""
    strat = _strategy(
        [_cmp({"name": "PM High Gap (%)"}, "GREATER_THAN_OR_EQUAL", 50)],
        bias="short",
        time_windows=[{"from_time": "07:00", "to_time": "08:00"}],
        risk={"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 30}},
    )
    assert not _plan_special(strat)
    df = _make_day_df(seed=89)
    ds = _make_daily_stats(df)
    _assert_equivalent(strat, df, ds)


# ─── 7. Causalidad PM en nativo (regresión lookahead) ─────────────────────

def test_pm_high_gap_nativo_es_causal():
    """Día sintético: plano a 1.00 hasta 08:00, rampa a 1.60 entre 08:00-09:00.
    Con prev_close=1.0, el gap≥50% NO puede dispararse antes de que el cummax
    cruce 1.5 (misma construcción que tests/test_pm_lookahead.py)."""
    ts = pd.date_range("2024-11-12 04:00", "2024-11-12 10:59", freq="1min")
    n = len(ts)
    minutes = ts.hour * 60 + ts.minute
    price = np.where(minutes < 480, 1.0,
                     np.where(minutes < 540, 1.0 + 0.6 * (minutes - 480) / 60.0, 1.55))
    df = pd.DataFrame({"timestamp": ts, "open": price, "high": price * 1.001,
                       "low": price * 0.999, "close": price,
                       "volume": np.full(n, 1000)})
    ds = {"prev_close": 1.0, "previous_close": 1.0, "pm_high": float(df["high"].max())}
    strat = _strategy([_cmp({"name": "PM High Gap (%)"}, "GREATER_THAN_OR_EQUAL", 50)],
                      bias="short")
    compiled = compile_strategy_def(strat)
    native = translate_strategy_native(_make_arrays(df), compiled, ds)
    entries = np.asarray(native["entries"], dtype=bool)
    assert entries.any(), "la rampa cruza 50%: debería haber señal"
    first = np.flatnonzero(entries)[0]
    cummax = np.fmax.accumulate(np.where((minutes >= 240) & (minutes < 570),
                                         df["high"].values, np.nan))
    first_legit = np.flatnonzero(cummax >= 1.5)[0]
    assert first >= first_legit, (
        f"lookahead nativo: señal en barra {first} antes de que el PMH corriente "
        f"cruce 1.5 (barra {first_legit})"
    )
    _assert_equivalent(strat, df, ds)
