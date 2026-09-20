# -*- coding: utf-8 -*-
"""Escalado automatico del crudo (20-sep-2026, tarde): rotacion por ranking
con suelo por estrategia y freno por caida de la cuenta."""
import copy

import pytest

from app.services import escalado_auto as ea
from app.services import portfolio_lab_raw as plr


def test_suelo_conserva_la_suma_y_nadie_baja_del_minimo():
    assert ea.aplicar_suelo([4.0, 2.0, 1.0], 1.0) == [4.0, 2.0, 1.0]
    s = ea.aplicar_suelo([5.0, 2.0, 0.0], 1.0)
    assert s[2] == pytest.approx(1.0) and sum(s) == pytest.approx(7.0) and s[0] > s[1] > s[2]
    # Lo que falta se quita en proporcion a lo que cada una tiene por encima del suelo.
    assert (5.0 - s[0]) / (2.0 - s[1]) == pytest.approx(4.0 / 1.0)
    # Si el suelo x n no cabe en la suma, todas al suelo.
    assert ea.aplicar_suelo([3.0, 0.0, 0.0], 2.0) == [2.0, 2.0, 2.0]
    assert ea.aplicar_suelo([3.0, 0.0], 0.0) == [3.0, 0.0]


def test_rotacion_ordena_por_lo_rendido_y_respeta_el_suelo():
    cfg = ea.rotation_cfg({"enabled": True, "lookback_days": 5, "rebalance": "N", "every_days": 5, "pattern": [4, 2, 0], "min_pct": 0.5}, 3)
    rot = ea.Rotacion(cfg, [1.0, 1.0, 1.0], ["a", "b", "c"])
    dias = [f"2026-01-{k:02d}" for k in range(1, 16)]
    # 5 primeros dias: sin historia -> los % del paso 1
    for d in dias[:5]:
        assert rot.sizes_para(d) == [1.0, 1.0, 1.0]
        rot.registrar(d, [0.001, 0.003, -0.001])        # c pierde, b es la mejor
    s = rot.sizes_para(dias[5])
    # b la mejor (4), a segunda (2), c tercera (0 -> suelo 0,5; el 0,5 que falta
    # sale de b y a en proporcion a lo que tienen por encima del suelo).
    assert s[2] == pytest.approx(0.5) and s[1] > s[0] > s[2] and sum(s) == pytest.approx(6.0)
    assert s[1] == pytest.approx(4.0 - 0.5 * 3.5 / 5.0) and s[0] == pytest.approx(2.0 - 0.5 * 1.5 / 5.0)
    assert rot.ranks == [2, 1, 3]
    for d in dias[5:10]:
        rot.sizes_para(d)
        rot.registrar(d, [0.004, 0.0, 0.002])           # ahora a es la mejor, c segunda: c vuelve aunque iba al suelo
    s2 = rot.sizes_para(dias[10])
    assert rot.ranks == [1, 3, 2] and s2[0] > s2[2] > s2[1] and s2[1] == pytest.approx(0.5)
    inf = rot.informe()
    assert inf["rebalanceos"] == 3 and inf["cambios_de_ranking"] == 1
    assert inf["hoy"]["ranks"] == [1, 3, 2] and inf["hoy"]["total_pct"] == pytest.approx(6.0)


def test_rotacion_mensual_y_semanal_rebalancean_cuando_toca():
    cfg = ea.rotation_cfg({"enabled": True, "lookback_days": 5, "rebalance": "M", "pattern": [3, 1]}, 2)
    rot = ea.Rotacion(cfg, [2.0, 2.0], ["a", "b"])
    for d in ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12", "2026-02-02"]:
        rot.sizes_para(d); rot.registrar(d, [0.001, 0.002])
    assert [p["from"] for p in rot.periods] == ["2026-01-05", "2026-02-02"]
    cfg_w = ea.rotation_cfg({"enabled": True, "lookback_days": 5, "rebalance": "W", "pattern": [3, 1]}, 2)
    rot_w = ea.Rotacion(cfg_w, [2.0, 2.0], ["a", "b"])
    for d in ["2026-01-05", "2026-01-06", "2026-01-12", "2026-01-13", "2026-01-19"]:
        rot_w.sizes_para(d); rot_w.registrar(d, [0.001, 0.002])
    assert [p["from"] for p in rot_w.periods] == ["2026-01-05", "2026-01-12", "2026-01-19"]


def test_freno_frena_y_suelta_por_la_caida():
    fr = ea.Freno(ea.brake_cfg({"enabled": True, "dd_pct": 10, "mult": 0.5, "exit_dd_pct": 5}), 1000.0)
    assert fr.mult_para("d1", 1000.0) == 1.0
    fr.registrar(1100.0)                       # maximo 1.100
    assert fr.mult_para("d2", 1000.0) == 1.0   # -9 %: no frena
    assert fr.mult_para("d3", 980.0) == 0.5    # -10,9 %: frena
    assert fr.mult_para("d4", 1030.0) == 0.5   # -6,4 %: sigue frenado
    assert fr.mult_para("d5", 1050.0) == 1.0   # -4,5 %: suelta
    inf = fr.informe(1050.0)
    assert inf["dias_frenado"] == 2 and inf["episodios"] == 1 and inf["hoy"]["frenado"] is False
    real = ea.freno_sobre_curva(ea.brake_cfg({"enabled": True, "dd_pct": 10, "mult": 0.5, "exit_dd_pct": 5}), [1100.0, 950.0, 960.0], 1000.0)
    assert real["hoy"]["frenado"] is True and real["hoy"]["mult"] == 0.5 and real["hoy"]["dd_pct"] == pytest.approx(-12.73, abs=0.01)


def _run_capital(sid, ticker, date, entry, exitp, size=500):
    return {
        "strategy_id": sid, "run_id": f"run-{sid}", "name": sid,
        "backtest_params": {"init_cash": 10000.0, "risk_type": "FIXED", "risk_r": 100.0, "slippage": 0.0, "size_by_sl": False},
        "equity": [],
        "trades": [{
            "date": date, "ticker": ticker, "direction": "Short",
            "entry_time": f"{date} 04:10:00", "exit_time": f"{date} 04:30:00",
            "avg_entry_price": entry, "entry_price": entry, "exit_price": exitp,
            "size": size, "init_size": size, "init_price": entry,
            "pnl": (entry - exitp) * size, "pnl_with_locates": (entry - exitp) * size,
            "fees": 0.0, "stop_loss": entry * 1.1, "exit_reason": "TP",
        }],
    }


def _dos_estrategias(dias=60):
    """a gana el 1 % cada dia; b pierde el 1 % cada dia (misma posicion)."""
    a = _run_capital("a", "AAA", "2026-01-02", 1.0, 0.99); a["trades"] = []
    b = _run_capital("b", "BBB", "2026-01-02", 1.0, 1.01); b["trades"] = []
    for k in range(dias):
        d = f"2026-{1 + k // 20:02d}-{1 + k % 20:02d}"
        for r, exitp in ((a, 0.99), (b, 1.01)):
            t = copy.deepcopy(_run_capital(r["strategy_id"], "AAA" if r is a else "BBB", d, 1.0, exitp)["trades"][0])
            r["trades"].append(t)
    return [a, b]


def test_en_el_motor_la_rotacion_da_el_patron_a_la_mejor_y_hay_hoy():
    runs = _dos_estrategias()
    cfg = {"capital": 100000.0, "cap_mode": "skip", "default_exec": {"sizing": "auto", "size_value": 2.0, "size_unit": "pct"}}
    sin = plr.simulate(runs, cfg)
    con = plr.simulate(runs, dict(cfg, rotation={"enabled": True, "lookback_days": 10, "rebalance": "N", "every_days": 10, "pattern": [3, 1], "min_pct": 0.5}))
    assert sin["rotation"] is None and con["rotation"] is not None
    r = con["rotation"]
    # Primer periodo sin historia: 2/2; desde el segundo, a (gana) 3 y b (pierde) 1.
    assert r["periods"][0]["sizes"] == [2.0, 2.0] and r["periods"][0]["ranks"] is None
    assert r["periods"][1]["sizes"] == [3.0, 1.0] and r["periods"][1]["ranks"] == [1, 2]
    assert r["hoy"]["sizes"] == [3.0, 1.0] and r["hoy"]["ranks"] == [1, 2] and r["hoy"]["total_pct"] == 4.0
    # Y gana mas que fijo 2/2: la misma suma, mas a la buena.
    assert con["equity"][-1] > sin["equity"][-1]
    # El tamano de a en el segundo periodo es 3 % del equity del dia.
    T = con["trades"]
    k = next(i for i in range(len(T["date"])) if T["date"][i] >= r["periods"][1]["from"] and T["ticker"][i] == "AAA")
    i_dia = con["calendar"].index(T["date"][k]); eq_open = con["equity"][i_dia - 1]
    assert T["notional"][k] == pytest.approx(0.03 * eq_open, rel=1e-3)


def test_en_el_motor_el_freno_reduce_la_caida():
    a = _run_capital("a", "AAA", "2026-01-02", 1.0, 0.99); a["trades"] = []
    # 15 dias perdiendo el 2 % de la posicion, luego 105 ganando el 1 %.
    for k in range(120):
        d = f"2026-{1 + k // 20:02d}-{1 + k % 20:02d}"
        t = copy.deepcopy(_run_capital("a", "AAA", d, 1.0, 1.02 if k < 15 else 0.99)["trades"][0])
        a["trades"].append(t)
    cfg = {"capital": 100000.0, "cap_mode": "skip", "default_exec": {"sizing": "auto", "size_value": 50.0, "size_unit": "pct"}}
    sin = plr.simulate([a], cfg)
    con = plr.simulate([a], dict(cfg, brake={"enabled": True, "dd_pct": 5, "mult": 0.5, "exit_dd_pct": 2}))
    def dd(eq):
        peak = 100000.0; m = 0.0
        for e in eq:
            peak = max(peak, e); m = min(m, e / peak - 1)
        return m
    assert con["brake"]["episodios"] >= 1 and con["brake"]["dias_frenado"] > 0
    assert dd(con["equity"]) > dd(sin["equity"])          # menos caida (menos negativa)
    assert con["brake"]["hoy"]["frenado"] is False           # al final, recuperado y suelto


def test_metrica_por_hora_premia_a_la_rapida():
    """a gana 0,3 % al dia en 6 horas; b gana 0,2 % al dia en 1 hora: por lo
    ganado, a; por hora en mercado, b."""
    cfg_r = ea.rotation_cfg({"enabled": True, "lookback_days": 5, "rebalance": "N", "every_days": 5, "pattern": [3, 1], "metric": "return"}, 2)
    cfg_h = ea.rotation_cfg({"enabled": True, "lookback_days": 5, "rebalance": "N", "every_days": 5, "pattern": [3, 1], "metric": "per_hour"}, 2)
    rr, rh = ea.Rotacion(cfg_r, [2.0, 2.0], ["a", "b"]), ea.Rotacion(cfg_h, [2.0, 2.0], ["a", "b"])
    for k in range(5):
        d = f"2026-01-{k + 1:02d}"
        for r in (rr, rh):
            r.sizes_para(d); r.registrar(d, [0.003, 0.002], [1, 1], [6.0, 1.0])
    assert rr.sizes_para("2026-01-06") == [3.0, 1.0]
    assert rh.sizes_para("2026-01-06") == [1.0, 3.0]
