# -*- coding: utf-8 -*-
"""Modo «En cuanto se cumpla» + % Fade (3 sesiones) + juegos (2026-10-01).

Escenarios con un día sintético: pico en 10.1 (highs = close*1.01 en tramo
plano a 10.0) y tramos de caída construidos para dar un fade EXACTO
(fade = (10.1 - close)/10.1*100 una vez pasado el pico). Entrada short en el
umbral elegido con `Bar Close <= cierre_para_fade(f)`; SL 50 % para que las
piernas de recuperación (desarme de juegos) no saquen el trade.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.strategy_engine import compile_strategy_def, translate_strategy  # noqa: E402
from app.services.indicators import compute_indicator  # noqa: E402
from app.services.portfolio_sim import simulate  # noqa: E402

PM_MAX = 10.1  # high del tramo plano (close 10.0 * 1.01)


def cierre_para_fade(f: float) -> float:
    return PM_MAX * (1 - f / 100.0)


def fade_esperado(close: np.ndarray) -> np.ndarray:
    return (PM_MAX - close) / PM_MAX * 100.0


def _dia(tramos):
    """tramos: [(bar_ini, bar_fin_excl, fade_pct)] — 420 velas 04:00-11:00."""
    ts = pd.date_range("2025-01-10 04:00", periods=420, freq="1min")
    close = np.full(420, 10.0)
    for a, b, f in tramos:
        close[a:b] = cierre_para_fade(f)
    df = pd.DataFrame({
        "ticker": "X", "timestamp": ts, "open": close, "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": 1000.0,
    })
    return df, ts, close


def _cond_entrada(f):
    return {"type": "group", "operator": "AND", "conditions": [
        {"type": "indicator_comparison", "source": {"name": "Bar Close"},
         "comparator": "LESS_THAN_OR_EQUAL", "target": cierre_para_fade(f), "timeframe": "1m"}]}


def _regla_when(umbral=20, j1=None, j2d=None, j2r=None, close_pct=100, hora="23:59"):
    r = {
        "hour": hora, "trigger": "when",
        "condition": {"type": "group", "operator": "AND", "conditions": [
            {"type": "indicator_comparison",
             "source": {"name": "% Fade", "fade_ref": "previous_max", "ap_session": "ap.PM"},
             "comparator": "GREATER_THAN", "target": umbral, "timeframe": "1m"}]},
        "action": "close_pct", "close_pct": close_pct, "stop_offset_pct": 0,
    }
    if j1 is not None:
        r["juego_cumplida_pct"] = j1
    if j2d is not None:
        r["juego_desde_pct"] = j2d
    if j2r is not None:
        r["juego_recorrido_pct"] = j2r
    return r


def _defn(reglas, entrada_f):
    return {
        "bias": "short",
        "entry_logic": {"timeframe": "1m", "root_condition": _cond_entrada(entrada_f)},
        "exit_logic": {"timeframe": "1m", "root_condition": None},
        "risk_management": {"sl_stop": 0.5, "scheduled_exits": reglas},
    }


def _corre(defn, df, close):
    sig = translate_strategy(df, defn)
    res = simulate(
        close=close, open_=close, high=close * 1.01, low=close * 0.99,
        entries=np.asarray(sig["entries"]), exits=np.asarray(sig["exits"]),
        direction="shortonly", init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        sl_stop=0.5, timestamps=df["timestamp"].values.astype("int64"),
        scheduled_exits=sig.get("scheduled_exits") or None,
    )
    return res, sig


def _sched(res):
    return [t for t in res["trades"] if t["exit_reason"] == "Scheduled Exit"]


def test_when_sin_juego_dispara_en_primera_vela_cumplida():
    # Sin juegos, aunque al entrar ya vaya cumplida: dispara en la primera
    # vela con posición en la que el fade > 20 (la vela de entrada no cuenta).
    df, ts, close = _dia([(0, 200, 0), (200, 420, 25)])
    res, _ = _corre(_defn([_regla_when()], 25), df, close)
    sched = _sched(res)
    assert len(sched) == 1
    assert 200 <= sched[0]["entry_idx"] <= 201
    assert 201 <= sched[0]["exit_idx"] <= 203
    assert fade_esperado(close)[sched[0]["exit_idx"]] > 20


def test_juego1_exige_umbral_mas_juego():
    # Entra a fade 25 (J1 armado) -> exige 30: con fade 25-35 no dispara hasta 35.
    df, ts, close = _dia([(0, 200, 0), (200, 260, 25), (260, 420, 35)])
    res, _ = _corre(_defn([_regla_when(j1=10)], 25), df, close)
    sched = _sched(res)
    assert len(sched) == 1
    assert 260 <= sched[0]["exit_idx"] <= 261
    # Y sin juego habría disparado en la entrada: el juego APLAZÓ el cierre.
    assert fade_esperado(close)[sched[0]["exit_idx"]] > 30


def test_juego1_desarma_al_bajar_del_umbral():
    # Armado a 25, el fade baja de 20 (reancla) -> desarme -> dispara al 20 normal.
    df, ts, close = _dia([(0, 200, 0), (200, 260, 25), (260, 340, 15), (340, 420, 22)])
    res, _ = _corre(_defn([_regla_when(j1=10)], 25), df, close)
    sched = _sched(res)
    assert len(sched) == 1
    assert 340 <= sched[0]["exit_idx"] <= 341
    assert 20 < fade_esperado(close)[sched[0]["exit_idx"]] <= 22 + 1e-6


def test_juego2_exige_recorrido_desde_entrada():
    # Entra a fade 18 (cerca, sin llegar al umbral) -> J2: exige 18+10=28.
    df, ts, close = _dia([(0, 200, 0), (200, 260, 18), (260, 300, 26), (300, 420, 29)])
    res, _ = _corre(_defn([_regla_when(j2d=15, j2r=10)], 18), df, close)
    sched = _sched(res)
    assert len(sched) == 1
    assert 300 <= sched[0]["exit_idx"] <= 301
    assert fade_esperado(close)[sched[0]["exit_idx"]] >= 28


def test_juego2_desarma_al_bajar_del_desde():
    # Armado a 18; el fade baja de 15 -> desarme -> dispara al 20 normal.
    df, ts, close = _dia([(0, 200, 0), (200, 240, 18), (240, 340, 12), (340, 420, 22)])
    res, _ = _corre(_defn([_regla_when(j2d=15, j2r=10)], 18), df, close)
    sched = _sched(res)
    assert len(sched) == 1
    assert 340 <= sched[0]["exit_idx"] <= 341
    assert 20 < fade_esperado(close)[sched[0]["exit_idx"]] <= 22 + 1e-6


def test_juego2_no_se_arma_si_entra_bajo_del_desde():
    # Entra a fade 8 (< desde 15): sin juego -> dispara al cruzar 20.
    df, ts, close = _dia([(0, 200, 0), (200, 260, 8), (260, 420, 22)])
    res, _ = _corre(_defn([_regla_when(j2d=15, j2r=10)], 8), df, close)
    sched = _sched(res)
    assert len(sched) == 1
    assert 260 <= sched[0]["exit_idx"] <= 261
    assert 20 < fade_esperado(close)[sched[0]["exit_idx"]] <= 22 + 1e-6


def test_when_ignora_la_hora():
    # La hora del JSON (23:59) NO acota el modo when: ya dispara por la condición.
    monkey = compile_strategy_def(_defn([_regla_when(hora="23:59")], 25))
    regla = monkey["scheduled_exits"][0]
    assert regla["trigger"] == "when" and regla["hour_min"] == (0, 0)


def test_trigger_ausente_equivalente_a_hour(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    regla_hour = _regla_when(hora="08:30")
    regla_hour["trigger"] = "hour"
    con = compile_strategy_def(_defn([regla_hour], 25))
    sin = compile_strategy_def(_defn([{k: v for k, v in regla_hour.items() if k != "trigger"}], 25))
    for c in (con, sin):
        r = c["scheduled_exits"][0]
        assert r["trigger"] == "hour" and r["hour_min"] == (8, 30)
        assert r["juego_cumplida"] is None and r["root_condition_estricto"] is None


def test_juegos_en_modo_hour_se_ignoran(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    regla = _regla_when(hora="08:00", j1=10, j2d=15, j2r=10)
    regla["trigger"] = "hour"
    c = compile_strategy_def(_defn([regla], 25))
    r = c["scheduled_exits"][0]
    assert r["juego_cumplida"] is None and r["juego_desde"] is None
    assert r["root_condition_estricto"] is None
    # Y en hour el disparo sigue siendo a la hora exacta (fade > 20 ya a las 08:00).
    df, ts, close = _dia([(0, 200, 0), (200, 420, 25)])
    res, _ = _corre(_defn([regla], 25), df, close)
    sched = _sched(res)
    assert len(sched) == 1
    idx_h = int(np.searchsorted(ts, pd.Timestamp("2025-01-10 08:00")))
    assert sched[0]["exit_idx"] in (idx_h, idx_h + 1)


def test_juego_forma_invalida_se_ignora_con_warning(monkeypatch, caplog):
    # Comparador LESS_THAN: el juego exige > / >= -> se ignora, la regla vale.
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    regla = _regla_when()
    regla["condition"]["conditions"][0]["comparator"] = "LESS_THAN"
    regla["juego_cumplida_pct"] = 10
    c = compile_strategy_def(_defn([regla], 25))
    r = c["scheduled_exits"][0]
    assert r["juego_cumplida"] is None and r["root_condition_estricto"] is None


def test_fade_tres_sesiones():
    # PM plano 10.0 (PMH high 10.1) -> dip 9.4 en RTH -> máx. RTH 10.605 -> caída 8.5.
    ts = pd.date_range("2025-01-10 04:00", periods=420, freq="1min")
    close = np.full(420, 10.0)
    close[330:360] = 9.4    # 09:30-09:59 dip
    close[360:390] = 10.5   # 10:00-10:29 máximo RTH (high 10.605)
    close[390:] = 8.5       # 10:30 caída
    df = pd.DataFrame({
        "ticker": "X", "timestamp": ts, "open": close, "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": 1000.0,
    })
    fades = {}
    for ses in ("ap.PM", "ap.PM_ONLY", "ap.RTH"):
        s = compute_indicator("% Fade", df, fade_ref="previous_max", ap_session=ses)
        fades[ses] = s.values
    en_dip, en_caida = 340, 400
    # Primera vela RTH (330): sin máximo RTH previo -> NaN. En el dip (335):
    # el RTH mide desde el máximo de las velas RTH ya vistas (9.494).
    assert fades["ap.RTH"][330] != fades["ap.RTH"][330]  # NaN
    assert abs(fades["ap.RTH"][335] - (9.494 - 9.4) / 9.494 * 100) < 0.01
    esperado_pmh = (10.1 - 9.4) / 10.1 * 100
    assert abs(fades["ap.PM_ONLY"][en_dip] - esperado_pmh) < 0.01
    assert abs(fades["ap.PM"][en_dip] - esperado_pmh) < 0.01
    # En la caída tras el máximo RTH: «solo PM» sigue anclado al PMH (10.1);
    # «PM+RTH» y «RTH» reanclan al máximo RTH (10.605).
    esperado_solo_pm = (10.1 - 8.5) / 10.1 * 100
    esperado_con_rth = (10.605 - 8.5) / 10.605 * 100
    assert abs(fades["ap.PM_ONLY"][en_caida] - esperado_solo_pm) < 0.01
    assert abs(fades["ap.PM"][en_caida] - esperado_con_rth) < 0.01
    assert abs(fades["ap.RTH"][en_caida] - esperado_con_rth) < 0.01
    # El máximo RTH (10.605) es mayor que el PMH (10.1): la misma caída da un
    # fade MAYOR medido desde el reancla RTH que desde el PMH congelado —
    # «solo PM» NO reancló con el máximo RTH (15.84 vs 19.85).
    assert fades["ap.PM_ONLY"][en_caida] < fades["ap.PM"][en_caida]


def test_piramide_add_no_rearma_la_regla():
    # La regla dispara una vez (fade > 20); un add de pirámide posterior no la
    # rearma: SIEMPRE un único Scheduled Exit.
    df, ts, close = _dia([(0, 200, 0), (200, 420, 25)])
    defn = _defn([_regla_when(close_pct=50)], 25)
    defn["pyramiding"] = {"timeframe": "1m", "levels": [{
        "action": "add", "capital_pct": 10, "times": 1,
        "root_condition": {"type": "group", "operator": "AND", "conditions": [
            {"type": "indicator_comparison", "source": {"name": "Bar Close"},
             "comparator": "GREATER_THAN_OR_EQUAL", "target": 0, "timeframe": "1m"}]},
    }]}
    res, _ = _corre(defn, df, close)
    assert len(_sched(res)) == 1


def test_pydantic_acepta_trigger_juegos_y_pm_only():
    from app.schemas.strategy import StrategyCreate
    defn = {
        "name": "prueba-when-juegos", "bias": "short",
        "entry_logic": {"timeframe": "1m", "root_condition": _cond_entrada(25)},
        "risk_management": {"sl_stop": 0.05, "scheduled_exits": [
            {"hour": "00:00", "trigger": "when",
             "condition": {"type": "group", "operator": "AND", "conditions": [
                 {"type": "indicator_comparison",
                  "source": {"name": "% Fade", "fade_ref": "previous_max", "ap_session": "ap.PM_ONLY"},
                  "comparator": "GREATER_THAN_OR_EQUAL", "target": 20, "timeframe": "1m"}]},
             "juego_cumplida_pct": 10, "juego_desde_pct": 15, "juego_recorrido_pct": 10,
             "action": "close_pct", "close_pct": 50, "stop_offset_pct": 0}]},
    }
    s = StrategyCreate(**defn)
    r = s.risk_management.scheduled_exits[0]
    assert r.trigger == "when"
    assert r.juego_cumplida_pct == 10 and r.juego_desde_pct == 15 and r.juego_recorrido_pct == 10
    assert r.condition.conditions[0].source.ap_session == "ap.PM_ONLY"


def test_when_sin_reglas_ni_flag_no_cambia_nada(monkeypatch):
    monkeypatch.delenv("SCHEDULED_EXITS_ENABLED", raising=False)
    df, ts, close = _dia([(0, 200, 0), (200, 420, 25)])
    res, sig = _corre(_defn([_regla_when()], 25), df, close)
    assert not sig.get("scheduled_exits")
    assert not _sched(res)
