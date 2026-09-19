# -*- coding: utf-8 -*-
"""Criterios de margen y BP en el portfolio EN CRUDO (19-sep-2026): el barrido
cronologico de exposicion exige el margen del broker a cada entrada contra el
equity del dia; la que no cabe se salta (o se recorta con cap_mode=trim)."""
import pytest

from app.services import portfolio_lab_raw as plr


def _run(sid, ticker, t_in, t_out, size, entry=1.0, exitp=0.9, direction="Short"):
    """Una corrida con UN trade guardado (corto de `size` acciones a `entry`)."""
    return {
        "strategy_id": sid, "run_id": f"run-{sid}", "name": sid,
        "backtest_params": {"init_cash": 10000.0, "risk_type": "FIXED", "risk_r": 100.0,
                            "slippage": 0.0, "size_by_sl": False},
        "equity": [],
        "trades": [{
            "date": "2026-01-02", "ticker": ticker, "direction": direction,
            "entry_time": f"2026-01-02 {t_in}:00", "exit_time": f"2026-01-02 {t_out}:00",
            "avg_entry_price": entry, "entry_price": entry, "exit_price": exitp,
            "size": size, "init_size": size, "init_price": entry,
            "pnl": (entry - exitp) * size, "pnl_with_locates": (entry - exitp) * size,
            "fees": 0.0, "stop_loss": entry * 1.1, "exit_reason": "TP",
        }],
    }


def _cfg(margin, cap_mode="skip", sizes=(1000.0, 2900.0, 200.0)):
    # Tamano por capital en $ a 1 $/accion => acciones = $ fijados.
    return {
        "capital": 10000.0, "monthly_expenses": 0.0, "max_exposure_usd": 0.0, "cap_mode": cap_mode,
        "per_strategy": {f"s{k + 1}": {"sizing": "capital", "size_value": v, "size_unit": "usd"} for k, v in enumerate(sizes)},
        "margin": margin,
    }


def _runs():
    # 04:10 AAA 1.000 acc a 1 $ (corto < 2,50 $ => 2,50 $/acc = 2.500 $)
    # 04:15 BBB 2.900 acc => 7.250 $ (9.750 usados)
    # 04:20 CCC 200 acc => 500 $: NO cabe entero en 10.000 (quedan 250)
    return [_run("s1", "AAA", "04:10", "04:30", 1000), _run("s2", "BBB", "04:15", "04:40", 2900),
            _run("s3", "CCC", "04:20", "04:25", 200)]


def test_sin_margen_nada_cambia():
    out = plr.simulate(_runs(), _cfg(None))
    assert out["margin_report"] is None and out["config"]["margin"] is None
    assert out["cap_report"]["skipped"] == 0 and out["cap_report"]["trimmed"] == 0
    assert [s["totals"]["n_trades"] for s in out["per_strategy"]] == [1, 1, 1]


def test_margen_corta_al_que_no_cabe_en_orden_cronologico():
    out = plr.simulate(_runs(), _cfg({"enabled": True, "broker": "sagetrader", "capacity_pct": 100}))
    mr = out["margin_report"]
    assert mr["enabled"] and mr["broker"] == "sagetrader" and mr["skipped"] == 1 and mr["trimmed"] == 0
    assert out["cap_report"]["skipped"] == 1
    assert [s["totals"]["n_trades"] for s in out["per_strategy"]] == [1, 1, 0]
    # Pico del dia: 9.750 de 10.000 => 97,5 %
    assert mr["pico_max_pct"] == pytest.approx(97.5) and mr["pico_medio_pct"] == pytest.approx(97.5)
    assert out["config"]["margin"]["capacity_pct"] == 100


def test_margen_con_trim_recorta_a_lo_que_cabe():
    out = plr.simulate(_runs(), _cfg({"enabled": True, "broker": "sagetrader", "capacity_pct": 100}, cap_mode="trim"))
    mr = out["margin_report"]
    assert mr["skipped"] == 0 and mr["trimmed"] == 1
    # CCC se queda con 250 $ de margen => 100 acciones (la mitad)
    assert [s["totals"]["n_trades"] for s in out["per_strategy"]] == [1, 1, 1]
    assert out["per_strategy"][2]["totals"]["pnl_net"] == pytest.approx(0.1 * 100)
    assert mr["pico_max_pct"] == pytest.approx(100.0)


def test_con_mas_capacidad_o_largos_cabe_todo():
    out = plr.simulate(_runs(), _cfg({"enabled": True, "broker": "sagetrader", "capacity_pct": 200}))
    assert out["margin_report"]["skipped"] == 0 and out["margin_report"]["trimmed"] == 0
    # Largos: 25 % del valor => 1.000 + 2.900 + 200 = 4.100 $ nocional => 1.025 $ de margen
    runs = [_run("s1", "AAA", "04:10", "04:30", 1000, direction="Long", exitp=1.1),
            _run("s2", "BBB", "04:15", "04:40", 2900, direction="Long", exitp=1.1),
            _run("s3", "CCC", "04:20", "04:25", 200, direction="Long", exitp=1.1)]
    out = plr.simulate(runs, _cfg({"enabled": True, "broker": "sagetrader", "capacity_pct": 100}))
    assert out["margin_report"]["skipped"] == 0
    assert out["margin_report"]["pico_max_pct"] == pytest.approx(10.25)


def test_la_salida_libera_margen():
    # CCC entra a las 04:31, cuando AAA ya ha salido (04:30): cabe.
    runs = [_run("s1", "AAA", "04:10", "04:30", 1000), _run("s2", "BBB", "04:15", "04:40", 2900),
            _run("s3", "CCC", "04:31", "04:35", 200)]
    out = plr.simulate(runs, _cfg({"enabled": True, "broker": "sagetrader", "capacity_pct": 100}))
    assert out["margin_report"]["skipped"] == 0
    assert [s["totals"]["n_trades"] for s in out["per_strategy"]] == [1, 1, 1]
