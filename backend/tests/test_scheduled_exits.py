# -*- coding: utf-8 -*-
"""Salida programada condicional (2026-09-28) — tests.

Cubre: sin flag no compila nada; compile+translate de reglas; disparo único a
la hora; cerrar X %; mover stop a BE (y que dispare en la vela siguiente);
múltiples reglas; y NO-REGRESIÓN: simulate sin scheduled_exits idéntico a
simulate con scheduled_exits=[] (mismo motor, misma llamada).
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.strategy_engine import compile_strategy_def, translate_strategy  # noqa: E402
from app.services.portfolio_sim import simulate  # noqa: E402


def _dia(p_final=12.0):
    ts = pd.date_range("2025-01-10 04:00", "2025-01-10 11:00", freq="1min")
    n = len(ts)
    close = np.concatenate([
        np.full(200, 10.0),                 # 04:00-07:20 plano
        np.linspace(10.0, 9.0, 100),        # cae (short a favor)
        np.linspace(9.0, p_final, n - 300),  # recuperación
    ])
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


def _cond_siempre():
    return {"type": "group", "operator": "AND", "conditions": [
        {"type": "indicator_comparison", "source": {"name": "Bar Close"},
         "comparator": "GREATER_THAN_OR_EQUAL", "target": 0, "timeframe": "1m"}]}


def _corre(defn, df, close, **kw):
    sig = translate_strategy(df, defn)
    return simulate(
        close=close, open_=close, high=close * 1.01, low=close * 0.99,
        entries=np.asarray(sig["entries"]), exits=np.asarray(sig["exits"]),
        direction="shortonly", init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        sl_stop=0.05, timestamps=df["timestamp"].values.astype("int64"),
        scheduled_exits=sig.get("scheduled_exits") or None, **kw,
    )


def test_sin_flag_no_compila_nada(monkeypatch):
    monkeypatch.delenv("SCHEDULED_EXITS_ENABLED", raising=False)
    c = compile_strategy_def(_defn([{"hour": "08:30", "action": "close_pct", "close_pct": 100}]))
    assert not c.get("scheduled_exits")


def test_con_flag_compila_y_traduce(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    c = compile_strategy_def(_defn([{"hour": "08:30", "condition": _cond_siempre(), "action": "move_stop"}]))
    assert len(c.get("scheduled_exits") or []) == 1 and c["scheduled_exits"][0]["hour_min"] == (8, 30)
    df, ts, close = _dia()
    sig = translate_strategy(df, _defn([{"hour": "08:30", "condition": _cond_siempre(), "action": "move_stop"}]))
    assert len(sig["scheduled_exits"]) == 1
    assert len(np.asarray(sig["scheduled_exits"][0]["cond"])) == len(df)


def test_cerrar_todo_a_la_hora(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    df, ts, close = _dia()
    res = _corre(_defn([{"hour": "08:30", "condition": _cond_siempre(), "action": "close_pct", "close_pct": 100}]), df, close)
    idx_h = int(np.searchsorted(ts, pd.Timestamp("2025-01-10 08:30")))
    sched = [t for t in res["trades"] if t["exit_reason"] == "Scheduled Exit"]
    assert len(sched) == 1
    assert sched[0]["exit_idx"] == idx_h
    # con la posición cerrada ya no hay más salidas después
    assert all(t["exit_idx"] <= idx_h for t in res["trades"])


def test_cerrar_50_deja_el_resto(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    df, ts, close = _dia(p_final=12.0)
    res = _corre(_defn([{"hour": "08:30", "condition": _cond_siempre(), "action": "close_pct", "close_pct": 50}]), df, close)
    sched = [t for t in res["trades"] if t["exit_reason"] == "Scheduled Exit"]
    assert len(sched) == 1
    total = sum(t["size"] for t in res["trades"] if t["exit_reason"] != "Scheduled Exit")
    # el 50% cerrado no puede ser TODO el tamaño
    assert sched[0]["size"] < total + sched[0]["size"]


def test_condicion_falsa_no_dispara(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    df, ts, close = _dia()
    cond_nunca = {"type": "group", "operator": "AND", "conditions": [
        {"type": "indicator_comparison", "source": {"name": "Bar Close"},
         "comparator": "LESS_THAN", "target": 0, "timeframe": "1m"}]}
    res = _corre(_defn([{"hour": "08:30", "condition": cond_nunca, "action": "close_pct", "close_pct": 100}]), df, close)
    assert not [t for t in res["trades"] if t["exit_reason"] == "Scheduled Exit"]


def test_move_stop_be_dispara_en_vela_siguiente(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    df, ts, close = _dia(p_final=12.0)
    res = _corre(_defn([{"hour": "08:30", "condition": _cond_siempre(), "action": "move_stop", "stop_offset_pct": 0.0}]), df, close)
    # el stop movido a la entrada: la primera salida tras la hora debe ser SL al precio de entrada
    idx_h = int(np.searchsorted(ts, pd.Timestamp("2025-01-10 08:30")))
    posteriores = [t for t in res["trades"] if t["exit_idx"] > idx_h]
    assert posteriores, "debe salir por el stop movido"
    primero = min(posteriores, key=lambda t: t["exit_idx"])
    assert primero["exit_reason"] == "SL"
    assert abs(primero["exit_price"] - 10.0) < 1e-9  # break-even = entrada


def test_varias_reglas_en_orden(monkeypatch):
    monkeypatch.setenv("SCHEDULED_EXITS_ENABLED", "true")
    df, ts, close = _dia()
    res = _corre(_defn([
        {"hour": "08:00", "condition": _cond_siempre(), "action": "close_pct", "close_pct": 50},
        {"hour": "09:00", "condition": _cond_siempre(), "action": "close_pct", "close_pct": 100},
    ]), df, close)
    sched = [t for t in res["trades"] if t["exit_reason"] == "Scheduled Exit"]
    assert len(sched) == 2 and sched[0]["exit_idx"] < sched[1]["exit_idx"]


def test_sin_reglas_bitidentico():
    df, ts, close = _dia()
    defn = _defn([])
    sig = translate_strategy(df, defn)
    a = simulate(close=close, open_=close, high=close * 1.01, low=close * 0.99,
                 entries=np.asarray(sig["entries"]), exits=np.asarray(sig["exits"]),
                 direction="shortonly", init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
                 sl_stop=0.05, timestamps=df["timestamp"].values.astype("int64"))
    b = simulate(close=close, open_=close, high=close * 1.01, low=close * 0.99,
                 entries=np.asarray(sig["entries"]), exits=np.asarray(sig["exits"]),
                 direction="shortonly", init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
                 sl_stop=0.05, timestamps=df["timestamp"].values.astype("int64"),
                 scheduled_exits=[])
    assert a["trades"] == b["trades"] and np.array_equal(a["equity"], b["equity"])
