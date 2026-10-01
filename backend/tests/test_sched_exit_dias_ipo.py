# -*- coding: utf-8 -*-
"""«Dias desde IPO (lago)» como operando de salidas programadas (2026-10-01).

Cubre: el indicador constante desde daily_stats (vía clásica y nativa) con
fallback NaN; la regla dispara / no dispara según el umbral de días; EQUAL
exacto (los días son enteros); sin dato no dispara (fail-safe, aviso una vez);
el detector del orquestador (_necesita_dias_ipo); la clave de cache del
qualifying cambia con el flag; y el nombre pasa el schema Pydantic.
No-regresión de salidas programadas sin reglas: test_sin_reglas_bitidentico en
test_scheduled_exits.py (se mantiene verde, este fichero no toca ese camino).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.indicators as indicators  # noqa: E402
from app.services.indicators import (  # noqa: E402
    compute_indicator, DAYS_SINCE_IPO_NAME,
)
from app.services.strategy_engine import (  # noqa: E402
    compile_strategy_def, translate_strategy, _compute_indicator_raw,
)
from app.services.portfolio_sim import simulate  # noqa: E402
from app.schemas.strategy import IndicatorConfig  # noqa: E402


def _dia():
    ts = pd.date_range("2025-01-10 04:00", "2025-01-10 11:00", freq="1min")
    n = len(ts)
    close = np.full(n, 10.0)
    df = pd.DataFrame({
        "ticker": "X", "timestamp": ts, "open": close, "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": 1000.0,
    })
    return df, ts, close


def _defn(reglas):
    return {
        "bias": "short",
        "entry_logic": {"timeframe": "1m", "root_condition": {"type": "group", "operator": "AND", "conditions": [
            {"type": "indicator_comparison", "source": {"name": "Bar Close"},
             "comparator": "GREATER_THAN_OR_EQUAL", "target": 0, "timeframe": "1m"}]}},
        "exit_logic": {"timeframe": "1m", "root_condition": None},
        "risk_management": {"sl_stop": 0.05, "scheduled_exits": reglas},
    }


def _regla_ipo(comparator="LESS_THAN_OR_EQUAL", dias=30):
    return {
        "hour": "08:30",
        "condition": {"type": "group", "operator": "AND", "conditions": [
            {"type": "indicator_comparison",
             "source": {"name": DAYS_SINCE_IPO_NAME},
             "comparator": comparator, "target": dias, "timeframe": "1m"}]},
        "action": "close_pct", "close_pct": 100, "stop_offset_pct": 0,
    }


def _corre(defn, df, close, ds):
    sig = translate_strategy(df, defn, ds)
    return simulate(
        close=close, open_=close, high=close * 1.01, low=close * 0.99,
        entries=np.asarray(sig["entries"]), exits=np.asarray(sig["exits"]),
        direction="shortonly", init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        sl_stop=0.05, timestamps=df["timestamp"].values.astype("int64"),
        scheduled_exits=sig.get("scheduled_exits") or None,
    )


def test_nombre_en_schema_pydantic():
    cfg = IndicatorConfig(name=DAYS_SINCE_IPO_NAME)
    assert cfg.name.value == DAYS_SINCE_IPO_NAME


def test_indicador_constante_en_dos_vias():
    df, ts, close = _dia()
    ds = {"days_since_first_day": 12}
    s_clasica = compute_indicator(DAYS_SINCE_IPO_NAME, df, daily_stats=ds)
    assert np.allclose(s_clasica.values, 12.0)
    s_nativa = _compute_indicator_raw(
        DAYS_SINCE_IPO_NAME, close, close * 1.01, close * 0.99, close,
        np.asarray(df["volume"], dtype=float), daily_stats=ds,
    )
    assert np.all(s_nativa == 12.0)


def test_nan_sin_dato_y_aviso_una_vez(monkeypatch, caplog):
    monkeypatch.setattr(indicators, "_DIAS_IPO_WARNED", False)
    df, ts, close = _dia()
    with caplog.at_level("WARNING"):
        s = compute_indicator(DAYS_SINCE_IPO_NAME, df, daily_stats={})
    assert s.isna().all()
    assert any("days_since_first_day" in r.message for r in caplog.records)
    # una sola vez por proceso: la segunda llamada no repite el aviso
    caplog.clear()
    with caplog.at_level("WARNING"):
        compute_indicator(DAYS_SINCE_IPO_NAME, df, daily_stats={})
    assert not any("days_since_first_day" in r.message for r in caplog.records)


def test_regla_menor_igual_dispara_y_no_dispara(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    df, ts, close = _dia()
    idx_h = int(np.searchsorted(ts, pd.Timestamp("2025-01-10 08:30")))
    # IPO reciente (10 días < 30): cierra el 100 % a las 08:30
    res = _corre(_defn([_regla_ipo()]), df, close, {"days_since_first_day": 10})
    sched = [t for t in res["trades"] if t["exit_reason"] == "Scheduled Exit"]
    assert len(sched) == 1 and sched[0]["exit_idx"] == idx_h
    # título con edad truncada (45 días): la regla no toca la posición
    res2 = _corre(_defn([_regla_ipo()]), df, close, {"days_since_first_day": 45})
    assert not [t for t in res2["trades"] if t["exit_reason"] == "Scheduled Exit"]


def test_day_0_cuenta_como_reciente(monkeypatch):
    # Semántica 6.1 (INFORME_BLOQUE6): el día 0 (IPO pura) SÍ es < 30.
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    df, ts, close = _dia()
    res = _corre(_defn([_regla_ipo(comparator="LESS_THAN", dias=30)]), df, close,
                 {"days_since_first_day": 0})
    assert [t for t in res["trades"] if t["exit_reason"] == "Scheduled Exit"]


def test_equal_solo_con_igualdad_exacta(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    df, ts, close = _dia()
    res = _corre(_defn([_regla_ipo(comparator="EQUAL", dias=0)]), df, close,
                 {"days_since_first_day": 0})
    assert [t for t in res["trades"] if t["exit_reason"] == "Scheduled Exit"]
    res2 = _corre(_defn([_regla_ipo(comparator="EQUAL", dias=0)]), df, close,
                  {"days_since_first_day": 1})
    assert not [t for t in res2["trades"] if t["exit_reason"] == "Scheduled Exit"]


def test_sin_dato_no_dispara(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    monkeypatch.setattr(indicators, "_DIAS_IPO_WARNED", True)  # aviso ya probado arriba
    df, ts, close = _dia()
    res = _corre(_defn([_regla_ipo()]), df, close, {})
    assert not [t for t in res["trades"] if t["exit_reason"] == "Scheduled Exit"]


def test_compilado_normaliza_el_nombre():
    monkey = compile_strategy_def(_defn([_regla_ipo()]))
    reglas = monkey.get("scheduled_exits") or []
    assert len(reglas) == 1
    src = reglas[0]["root_condition"]["conditions"][0]["source"]
    assert src["name"] == DAYS_SINCE_IPO_NAME


def test_detector_orquestador():
    from app.services.backtest_orchestrator import _necesita_dias_ipo
    assert _necesita_dias_ipo({"risk_management": {"scheduled_exits": [_regla_ipo()]}}) is True
    assert _necesita_dias_ipo({"risk_management": {"scheduled_exits": []}}) is False
    # también si el operando vive en una condición de entrada (futuro)
    entrada = {"entry_logic": {"root_condition": {"type": "group", "operator": "AND", "conditions": [
        {"type": "indicator_comparison", "source": {"name": DAYS_SINCE_IPO_NAME},
         "comparator": "LESS_THAN", "target": 30, "timeframe": "1m"}]}}}
    assert _necesita_dias_ipo(entrada) is True


def test_cache_key_distinta_con_flag():
    from app.services.data_service import _qualifying_cache_key
    sin = _qualifying_cache_key("d1", {}, None, None, None, "gap_day", False)
    con = _qualifying_cache_key("d1", {}, None, None, None, "gap_day", True)
    assert sin != con
