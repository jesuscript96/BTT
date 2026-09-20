# -*- coding: utf-8 -*-
"""Tamano por SETUP en el portfolio en crudo (20-sep-2026): la Kelly relativa
de cada tramo de precio (EV/sigma^2), estimada walk-forward por anos, como
multiplicador del % del paso 1; y el reparto por Kelly conjunta."""
import copy

import numpy as np
import pytest

from app.services import portfolio_lab_raw as plr
from app.services import setup_sizing as ss


def _cfg_setup(**over):
    cfg = {"enabled": True, "min_trades": 10, "shrink": 0, "clip_lo": 0.5, "clip_hi": 2.0, "estimate": "walk_forward",
           "ranges": [[0, 2], [2, None]]}
    cfg.update(over)
    return ss.setup_cfg(cfg)


def test_tabla_da_mas_al_tramo_con_mas_kelly_y_conserva_la_media():
    """Tramo barato: EV 1 % con sd 10 %; tramo caro: EV 4 % con sd 10 % ->
    f = 1 y 4: el caro x1,6 y el barato x0,4 -> acotado a 0,5, y la media
    ponderada por trades vuelve a 1."""
    muestras = []
    for k in range(200):
        ruido = 0.10 if k % 2 else -0.10
        muestras.append((f"2024-{1 + k // 28:02d}-{1 + k % 28:02d}", 1.0, 0.01 + ruido))
        muestras.append((f"2024-{1 + k // 28:02d}-{1 + k % 28:02d}", 5.0, 0.04 + ruido))
    cfg = _cfg_setup()
    tabla = ss.estimar_tabla(muestras, cfg, None)
    barato, caro = tabla
    assert barato["n"] == 200 and caro["n"] == 200 and barato["con_muestra"] and caro["con_muestra"]
    assert caro["f"] > barato["f"] > 0
    assert caro["m"] > 1.0 > barato["m"]
    assert caro["m"] <= 2.0 and barato["m"] >= 0.5
    media = (barato["m"] * barato["n"] + caro["m"] * caro["n"]) / 400
    assert media == pytest.approx(1.0, abs=1e-4)


def test_sin_muestra_o_sin_edge_va_a_uno():
    muestras = [(f"2024-01-{1 + k % 28:02d}", 1.0, -0.02) for k in range(50)] + [("2024-02-01", 5.0, 0.05)] * 3
    tabla = ss.estimar_tabla(muestras, _cfg_setup(), None)
    # El barato tiene muestra pero EV < 0 (f_ref <= 0 -> nada que normalizar): todo x1.
    assert [r["m"] for r in tabla] == [1.0, 1.0]
    assert tabla[1]["con_muestra"] is False
    # Con un tramo bueno de referencia, el que pierde va al minimo (clip_lo).
    buenas = [(f"2024-03-{1 + k % 28:02d}", 5.0, 0.03 + (0.02 if k % 2 else -0.02)) for k in range(50)]
    tabla2 = ss.estimar_tabla(muestras[:50] + buenas, _cfg_setup(), None)
    assert tabla2[0]["m"] == pytest.approx(0.5) and tabla2[1]["m"] > 1.0


def test_encogimiento_acerca_a_uno_con_poca_muestra():
    muestras = [(f"2024-01-{1 + k % 28:02d}", 1.0, 0.01 + (0.05 if k % 2 else -0.05)) for k in range(400)]
    muestras += [(f"2024-02-{1 + k % 28:02d}", 5.0, 0.04 + (0.05 if k % 2 else -0.05)) for k in range(12)]
    sin = ss.estimar_tabla(muestras, _cfg_setup(shrink=0), None)
    con = ss.estimar_tabla(muestras, _cfg_setup(shrink=50), None)
    assert con[1]["m"] > 1.0 and con[1]["m"] < sin[1]["m"]


def test_walk_forward_el_primer_ano_va_a_uno_y_el_segundo_usa_el_primero():
    muestras = [[]]
    for k in range(120):
        muestras[0].append((f"2024-{1 + k // 28:02d}-{1 + k % 28:02d}", 1.0, 0.01 + (0.05 if k % 2 else -0.05)))
        muestras[0].append((f"2024-{1 + k // 28:02d}-{1 + k % 28:02d}", 5.0, 0.04 + (0.05 if k % 2 else -0.05)))
    calendar = [f"2024-{1 + k // 28:02d}-{1 + k % 28:02d}" for k in range(120)] + ["2025-01-02", "2025-01-03"]
    m = ss.Multiplicadores(_cfg_setup(), muestras, calendar)
    assert m.mult(0, 5.0, "2024-03-01") == 1.0 and m.mult(0, 1.0, "2024-03-01") == 1.0
    assert m.mult(0, 5.0, "2025-01-02") > 1.0 > m.mult(0, 1.0, "2025-01-02")
    # La vigente (con todo) coincide con la del segundo ano (mismos datos).
    assert m.vigente[0][1]["m"] == pytest.approx(m.tablas["2025-01-01"][0][1]["m"])
    inf = m.informe(["s1"], ["capital"])
    assert inf["vigente"][0]["ranges"][1]["m"] > 1 and len(inf["por_ano"]) == 2


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


def test_en_la_simulacion_el_tramo_bueno_va_mas_grande_y_el_primer_ano_igual():
    """2024: un trade barato (1 $, EV 0,17 %) y uno caro (5 $, EV 2 %) cada dia; 2025:
    los mismos. Con el setup, en 2024 nada cambia (sin historia) y en 2025 el
    caro va con multiplicador > 1 y el barato < 1, con la media ponderada 1."""
    base = _run_capital("s1", "AAA", "2024-01-02", 1.0, 0.99)
    base["trades"] = []
    for ano in ("2024", "2025"):
        for k in range(100):
            d = f"{ano}-{1 + k // 25:02d}-{1 + k % 25:02d}"
            # barato: +1 % dos de cada tres, -1,5 % la otra (EV 0,17 %); caro: +4 % / -2 % (EV 2 %)
            for entry, exitp, tk in ((1.0, 0.99 if k % 3 else 1.015, "AAA"), (5.0, 4.80 if k % 3 else 5.10, "BBB")):
                t = copy.deepcopy(_run_capital("s1", tk, d, entry, exitp)["trades"][0])
                base["trades"].append(t)
    cfg = {"capital": 100000.0, "cap_mode": "skip", "default_exec": {"sizing": "auto", "size_value": 1.0, "size_unit": "pct"}}
    sin = plr.simulate([base], cfg)
    con = plr.simulate([base], dict(cfg, setup={"enabled": True, "min_trades": 10, "shrink": 0, "clip_lo": 0.5, "clip_hi": 2.0, "ranges": [[0, 2], [2, None]]}))
    assert con["setup"] is not None and sin["setup"] is None
    T = con["trades"]
    m24 = [T["setup_mult"][k] for k in range(len(T["date"])) if T["date"][k].startswith("2024")]
    m25_caro = [T["setup_mult"][k] for k in range(len(T["date"])) if T["date"][k].startswith("2025") and T["ticker"][k] == "BBB"]
    m25_barato = [T["setup_mult"][k] for k in range(len(T["date"])) if T["date"][k].startswith("2025") and T["ticker"][k] == "AAA"]
    assert all(m == 1.0 for m in m24)
    assert all(m > 1.0 for m in m25_caro) and all(m < 1.0 for m in m25_barato)
    assert (m25_caro[0] + m25_barato[0]) / 2 == pytest.approx(1.0, abs=2e-3)   # (redondeado a 3 decimales en la salida)
    # El tamano del caro en 2025 es el del paso 1 x su multiplicador.
    k_caro = next(k for k in range(len(T["date"])) if T["date"][k].startswith("2025") and T["ticker"][k] == "BBB")
    k_sin = next(k for k in range(len(sin["trades"]["date"])) if sin["trades"]["date"][k] == T["date"][k_caro] and sin["trades"]["ticker"][k] == "BBB")
    assert T["notional"][k_caro] / sin["trades"]["notional"][k_sin] == pytest.approx(T["setup_mult"][k_caro], rel=1e-3)
    assert con["per_strategy"][0]["cap_report"]["setup"] == 200
    assert con["setup"]["por_estrategia"][0]["distintos_de_1"] == 200
    # Y gana mas: mismo nocional medio, mas en el tramo con mas edge.
    assert con["equity"][-1] > sin["equity"][-1]


def test_kelly_conjunta_reparte_por_edge_y_correlacion():
    rng = np.random.default_rng(3)
    n = 600
    a = 0.004 + 0.02 * rng.standard_normal(n)
    b = np.roll(a, 300)                                # los mismos valores, descorrelacionados (y simetricos con a)
    c = 0.0005 + 0.02 * rng.standard_normal(n)         # casi sin edge
    d = a + 0.001 * rng.standard_normal(n)             # clon de a
    f = ss.kelly_conjunta(np.column_stack([a, b, c]), 10.0)
    assert f.sum() == pytest.approx(10.0, abs=1e-6)
    assert f[0] == pytest.approx(f[1], rel=0.05) and f[2] < 0.5 * f[0]
    f2 = ss.kelly_conjunta(np.column_stack([a, b, d]), 10.0)
    # a y su clon se reparten entre las dos lo que antes era de a; b (independiente) se queda con lo suyo.
    assert f2[0] + f2[2] == pytest.approx(f2[1], rel=0.3) and f2.sum() == pytest.approx(10.0, abs=1e-6)
    e, dd = ss.crecimiento(np.column_stack([a, b, c]), f)
    assert e > 1.0 and -1.0 < dd <= 0.0
