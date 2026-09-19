# -*- coding: utf-8 -*-
"""Kelly sobre la cuenta REAL (19-sep-2026): R diaria desde el PnL real y el
riesgo por trade usado, Kelly exacta de la ventana, y el reparto entre
estrategias por sus Kellys del backtest con los dos topes."""
import numpy as np
import pytest

from app.services.portfolio_lab_raw import kelly_cuenta_real


def _rows(n=60, seed=1):
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        d = f"2026-{1 + k // 28:02d}-{1 + k % 28:02d}"
        # dia tipico: +1,5 R de media con dispersion 3 R, riesgo 100 $ por trade
        out.append({"date": d, "pnl": float(rng.normal(150.0, 300.0))})
    return out


def test_r_diaria_en_usd_y_en_pct():
    rows = [{"date": "2026-01-02", "pnl": 200.0}, {"date": "2026-01-02", "pnl": -50.0}, {"date": "2026-01-05", "pnl": -100.0}]
    # $ fijos: 150/100 = 1,5 R y -1 R
    o = kelly_cuenta_real(rows, "usd", 100.0, 10000.0, 0.5, 5.0, 2.0, 0, [], 10000.0)
    assert [x["r"] for x in o["serie"]] == [1.5, -1.0]
    assert o["dias"] == 2 and o["nota"] and "sin muestra" in o["nota"] and o["total_pct"] is None
    # % del equity del dia: 1 % de 10.000 = 100 $ el primer dia; el segundo, 1 % de 10.150
    o = kelly_cuenta_real(rows, "pct", 1.0, 10000.0, 0.5, 5.0, 2.0, 0, [], 10000.0)
    assert o["serie"][0]["riesgo"] == pytest.approx(100.0) and o["serie"][1]["riesgo"] == pytest.approx(101.5)
    assert o["serie"][1]["r"] == pytest.approx(-100.0 / 101.5, rel=1e-6)


def test_reparto_por_kellys_del_backtest_con_topes():
    rows = _rows()
    est = [{"name": "A", "kelly_pct": 60.0}, {"name": "B", "kelly_pct": 30.0}, {"name": "C", "kelly_pct": 0.0}]
    o = kelly_cuenta_real(rows, "usd", 100.0, 10000.0, 0.5, 5.0, 2.0, 0, est, 20000.0)
    assert o["kelly_raw_pct"] is not None and o["kelly_raw_pct"] > 0
    shares = [p["share"] for p in o["per_strategy"]]
    assert shares == pytest.approx([2 / 3, 1 / 3, 0.0])
    # Ninguna pasa del tope por estrategia (2 %) y la suma no pasa del tope (5 %).
    apl = [p["risk_pct"] for p in o["per_strategy"]]
    assert all(a <= 2.0 + 1e-9 for a in apl) and sum(apl) <= 5.0 + 1e-9
    assert o["total_pct"] == pytest.approx(sum(apl))
    assert o["per_strategy"][0]["risk_usd"] == pytest.approx(20000.0 * apl[0] / 100.0)
    # Con Kelly pedida grande, el tope por estrategia actua antes que el de la suma.
    assert o["capped_strategy"] is True or o["capped"] is True


def test_ventana_solo_mira_los_ultimos_dias():
    rows = _rows(120)
    todo = kelly_cuenta_real(rows, "usd", 100.0, 10000.0, 0.5, 0.0, 0.0, 0, [], 10000.0)
    ult = kelly_cuenta_real(rows, "usd", 100.0, 10000.0, 0.5, 0.0, 0.0, 30, [], 10000.0)
    assert todo["dias_ventana"] == 120 and ult["dias_ventana"] <= 31
    assert ult["desde"] >= "2026-03-31"
