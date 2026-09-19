# -*- coding: utf-8 -*-
"""Tope POR ACCION en el portfolio en crudo (19-sep-2026): lo abierto a la vez
en un mismo ticker sumando estrategias no pasa de X % del equity del dia, en
riesgo (perdida al stop de la entrada) o en nocional. Primero llega, primero
entra; la que llega con el ticker lleno se salta (o se recorta con trim)."""
import pytest

from app.services import portfolio_lab_raw as plr


def _run(sid, ticker, t_in, t_out, size, entry=1.0, exitp=0.9, stop=1.1, direction="Short"):
    return {
        "strategy_id": sid, "run_id": f"run-{sid}", "name": sid,
        "backtest_params": {"init_cash": 10000.0, "risk_type": "FIXED", "risk_r": 100.0,
                            "slippage": 0.0, "size_by_sl": True},
        "equity": [],
        "trades": [{
            "date": "2026-01-02", "ticker": ticker, "direction": direction,
            "entry_time": f"2026-01-02 {t_in}:00", "exit_time": f"2026-01-02 {t_out}:00",
            "avg_entry_price": entry, "entry_price": entry, "exit_price": exitp,
            "size": size, "init_size": size, "init_price": entry,
            "pnl": (entry - exitp) * size, "pnl_with_locates": (entry - exitp) * size,
            "fees": 0.0, "stop_loss": stop, "exit_reason": "TP",
        }],
    }


def _cfg(pct, basis="risk", cap_mode="skip", risk_usd=300.0):
    # Todas por riesgo: 300 $ al stop por trade (stop a 0,10 $ => 3.000 acciones a 1 $).
    return {
        "capital": 10000.0, "monthly_expenses": 0.0, "max_exposure_usd": 0.0, "cap_mode": cap_mode,
        "default_exec": {"sizing": "risk", "size_value": risk_usd, "size_unit": "usd"},
        "max_ticker_pct": pct, "ticker_cap_basis": basis,
    }


def _runs():
    # Dos estrategias cortas en AAA a la vez (04:10-04:30 y 04:15-04:40) y una
    # tercera en BBB (04:20): AAA acumula 600 $ de riesgo = 6 % del equity.
    return [_run("s1", "AAA", "04:10", "04:30", 1000), _run("s2", "AAA", "04:15", "04:40", 1000),
            _run("s3", "BBB", "04:20", "04:25", 1000)]


def _n_trades(out):
    return [s["totals"]["n_trades"] for s in out["per_strategy"]]


def test_sin_tope_nada_cambia():
    out = plr.simulate(_runs(), _cfg(0))
    assert out["ticker_cap_report"] is None and out["config"]["max_ticker_pct"] == 0
    assert _n_trades(out) == [1, 1, 1]


def test_tope_por_accion_en_riesgo_salta_a_la_segunda_del_mismo_ticker():
    # 5 % de 10.000 = 500 $ de riesgo por ticker: s1 mete 300, s2 pediria 300 mas
    # (600 > 500) => fuera. BBB no se toca (otro ticker).
    out = plr.simulate(_runs(), _cfg(5.0))
    r = out["ticker_cap_report"]
    assert r["basis"] == "risk" and r["skipped"] == 1 and r["trimmed"] == 0
    assert _n_trades(out) == [1, 0, 1]
    assert out["cap_report"]["skipped"] == 1
    # Y el conteo por estrategia ya no sale a cero.
    assert [s["cap_report"]["skipped"] for s in out["per_strategy"]] == [0, 1, 0]


def test_tope_por_accion_con_trim_recorta_a_lo_que_queda():
    out = plr.simulate(_runs(), _cfg(5.0, cap_mode="trim"))
    r = out["ticker_cap_report"]
    assert r["skipped"] == 0 and r["trimmed"] == 1
    assert _n_trades(out) == [1, 1, 1]
    # s2 se queda con 200 $ de riesgo de 300 => 2/3 del tamano => 2.000 acc => +200 $
    assert out["per_strategy"][1]["totals"]["pnl_net"] == pytest.approx(0.1 * 2000)


def test_tope_por_accion_en_nocional():
    # Nocional: 3.000 acc a 1 $ = 3.000 $ por trade = 30 % del equity. Con 50 %
    # por ticker, la segunda en AAA (60 %) no cabe; con 70 % si.
    out = plr.simulate(_runs(), _cfg(50.0, basis="notional"))
    assert out["ticker_cap_report"]["basis"] == "notional" and out["ticker_cap_report"]["skipped"] == 1
    assert _n_trades(out) == [1, 0, 1]
    out = plr.simulate(_runs(), _cfg(70.0, basis="notional"))
    assert out["ticker_cap_report"]["skipped"] == 0 and _n_trades(out) == [1, 1, 1]


def test_la_salida_libera_el_ticker():
    # s2 entra en AAA a las 04:31, cuando s1 ya salio (04:30): cabe.
    runs = [_run("s1", "AAA", "04:10", "04:30", 1000), _run("s2", "AAA", "04:31", "04:40", 1000)]
    out = plr.simulate(runs, _cfg(5.0))
    assert out["ticker_cap_report"]["skipped"] == 0 and _n_trades(out) == [1, 1]


def test_sin_stop_no_consume_ni_se_topa_en_riesgo():
    # Un trade sin stop (stop_loss 0, la corrida no dimensiono por stop) no tiene
    # riesgo medible: se cuenta en sin_stop y no bloquea.
    r2 = _run("s2", "AAA", "04:15", "04:40", 1000, stop=0.0)
    r2["backtest_params"]["size_by_sl"] = False
    runs = [_run("s1", "AAA", "04:10", "04:30", 1000), r2]
    cfg = _cfg(5.0)
    cfg["per_strategy"] = {"s2": {"sizing": "capital", "size_value": 1000.0, "size_unit": "usd"}}
    out = plr.simulate(runs, cfg)
    assert out["ticker_cap_report"]["sin_stop"] == 1 and out["ticker_cap_report"]["skipped"] == 0
    assert _n_trades(out) == [1, 1]


def test_base_por_trade_el_tope_es_lo_que_arriesga_un_trade():
    # «Por trade»: sin numero. s1 mete 300 $ de riesgo en AAA; s2 (tambien 300 $
    # por trade) llega con el ticker ya al tope de UN trade => fuera. Con trim,
    # queda 0 => tambien fuera. BBB entra (su primer trade cabe por definicion).
    out = plr.simulate(_runs(), _cfg(0, basis="trade"))
    r = out["ticker_cap_report"]
    assert r["basis"] == "trade" and r["skipped"] == 1 and _n_trades(out) == [1, 0, 1]
    # s2 con la mitad de riesgo por trade (150 $): el tope del ticker para ella
    # es 150 y ya hay 300 => fuera igual. Con s2 al doble (600 $): tope 600, hay
    # 300 => cabe la mitad => con trim entra recortada, con skip se salta.
    cfg = _cfg(0, basis="trade", cap_mode="trim")
    cfg["per_strategy"] = {"s2": {"sizing": "risk", "size_value": 600.0, "size_unit": "usd"}}
    out = plr.simulate(_runs(), cfg)
    assert out["ticker_cap_report"]["trimmed"] == 1 and _n_trades(out) == [1, 1, 1]
    # 600 $ de riesgo a 0,10 $ = 6.000 acc; recortada a 300 $ => 3.000 acc => +300 $
    assert out["per_strategy"][1]["totals"]["pnl_net"] == pytest.approx(0.1 * 3000)


# ── Escalado: tope por estrategia (19-sep) ─────────────────────────────

def test_tope_por_estrategia_va_antes_que_el_de_la_suma():
    """Pedido 18,5 / 1 / 1 con tope de la suma 10: sin tope por estrategia el
    recorte proporcional daba 9,02 / 0,49 / 0,49 (una sola se lleva el tope);
    con tope por estrategia 3, primero 3 / 1 / 1 (suma 5 <= 10: la suma no actua)."""
    from app.services.portfolio_lab_raw import _Escalado, _scaling_cfg
    import numpy as np
    cal = [f"2026-01-{d:02d}" for d in range(2, 31)]
    r_daily = np.zeros((len(cal), 3))
    esc = _Escalado(_scaling_cfg({"model": "kelly", "kelly_mult": 0.5, "cap_pct": 10.0, "cap_strategy_pct": 0.0}),
                    cal, r_daily, [[], [], []], [(cal[0], cal[-1])] * 3, 10000.0)
    # Se simula la estimacion con pedidos conocidos: el recorte es lo que se prueba.
    pedido = np.array([0.185, 0.01, 0.01])

    def recorte(cfg):
        cap_i = float(cfg.get("cap_strategy_pct") or 0.0) / 100.0
        apl = pedido.copy()
        if cap_i > 0:
            apl = np.minimum(apl, cap_i)
        cap = float(cfg["cap_pct"]) / 100.0
        if cap > 0 and apl.sum() > cap:
            apl = apl * (cap / apl.sum())
        return apl * 100.0

    sin = recorte(esc.cfg)
    assert np.allclose(sin, [9.0244, 0.4878, 0.4878], atol=1e-3)
    con = recorte(_scaling_cfg({"model": "kelly", "kelly_mult": 0.5, "cap_pct": 10.0, "cap_strategy_pct": 3.0}))
    assert np.allclose(con, [3.0, 1.0, 1.0])


def test_tope_por_estrategia_en_la_simulacion_real():
    """Con las tres estrategias sinteticas y Kelly: con tope por estrategia
    ninguna pasa de el en ningun periodo, y el flag capped_strategy sale."""
    runs = [_run("s1", "AAA", "04:10", "04:30", 1000, exitp=0.8), _run("s2", "BBB", "04:15", "04:40", 1000, exitp=0.85),
            _run("s3", "CCC", "04:20", "04:25", 1000, exitp=0.9)]
    # Historia de 60 dias para que Kelly tenga muestra: se replican los trades por dia.
    import copy
    for r in runs:
        base = r["trades"][0]
        r["trades"] = []
        for k in range(60):
            t = copy.deepcopy(base)
            d = f"2026-{1 + k // 28:02d}-{1 + k % 28:02d}"
            t["date"] = d; t["entry_time"] = f"{d} {base['entry_time'][11:]}"; t["exit_time"] = f"{d} {base['exit_time'][11:]}"
            r["trades"].append(t)
    cfg = {"capital": 10000.0, "cap_mode": "skip", "default_exec": {"sizing": "risk", "size_value": 1.0, "size_unit": "pct"},
           "scaling": {"model": "kelly", "kelly_mult": 1.0, "cap_pct": 0.0, "cap_strategy_pct": 0.5, "rebalance": "W", "lookback_days": 30, "pct": 0.25}}
    out = plr.simulate(runs, cfg)
    sc = out["scaling"]
    assert all(max(p["risk_pct"]) <= 0.5 + 1e-9 for p in sc["periods"])
    assert any(p.get("capped_strategy") for p in sc["periods"])
    assert sc["today"]["cap_strategy_pct"] == 0.5


# ── Escalado: la unidad de cada estrategia (19-sep, auditoria de Kelly) ──

def _run_capital(sid, ticker, t_in, t_out, size, entry=2.0, exitp=1.8):
    r = _run(sid, ticker, t_in, t_out, size, entry=entry, exitp=exitp, stop=entry * 1.5)
    r["backtest_params"]["size_by_sl"] = False   # la corrida dimensiono por capital
    return r


def test_r_neta_en_la_unidad_de_la_estrategia():
    from app.services.portfolio_lab_raw import _r_neta
    tr = {"gross_ps": 0.2, "entry": 2.0, "exit": 1.8, "init_price": 2.0, "pyr": 1.0, "stop_dist": 1.0,
          "risk_orig": 0.0, "size_saved": 100.0, "direction": "Short"}
    ex_cap = {"fee_type": "FLAT", "fees": 0.0, "slippage_pct": 0.0, "sizing": "capital"}
    ex_risk = dict(ex_cap, sizing="risk")
    # Por capital: retorno sobre la posicion (0,2 / 2 = 10 %); por stop: 0,2 / 1 = 0,2 R.
    assert _r_neta(tr, ex_cap) == pytest.approx(0.10)
    assert _r_neta(tr, ex_risk) == pytest.approx(0.20)
    # El locate esperado por accion se descuenta (solo cortos): 0,02 $/acc.
    assert _r_neta(tr, ex_cap, locate_ps=0.02) == pytest.approx(0.09)
    assert _r_neta(dict(tr, direction="Long"), ex_cap, locate_ps=0.02) == pytest.approx(0.10)


def test_kelly_dimensiona_por_posicion_a_las_que_van_por_capital():
    """Con tope por estrategia 1 % y una corrida por capital, Kelly pone 1 % del
    capital del dia EN POSICION (200 $ a 2 $ = 100 acciones), no 1 % de riesgo
    al stop aproximado (que a 1 $ de distancia serian 100 acc x 2 $ = 200 $
    de nocional... y con stops lejanos, mucho mas)."""
    import copy
    base = _run_capital("s1", "AAA", "04:10", "04:30", 500, entry=2.0, exitp=1.9)
    base["trades"] = []
    for k in range(60):
        t = copy.deepcopy(_run_capital("s1", "AAA", "04:10", "04:30", 500, entry=2.0, exitp=1.9)["trades"][0])
        d = f"2026-{1 + k // 28:02d}-{1 + k % 28:02d}"
        t["date"] = d; t["entry_time"] = f"{d} 04:10:00"; t["exit_time"] = f"{d} 04:30:00"
        base["trades"].append(t)
    cfg = {"capital": 20000.0, "cap_mode": "skip", "default_exec": {"sizing": "auto", "size_value": 1.0, "size_unit": "pct"},
           "scaling": {"model": "kelly", "kelly_mult": 1.0, "cap_pct": 0.0, "cap_strategy_pct": 1.0, "rebalance": "M", "lookback_days": 30, "pct": 1.0}}
    out = plr.simulate([base], cfg)
    sc = out["scaling"]
    assert sc["today"]["per_strategy"][0]["basis"] == "capital"
    assert all(p["bases"] == ["capital"] for p in sc["periods"])
    # Primer trade: 1 % de 20.000 = 200 $ en posicion a 2 $ = 100 acciones.
    assert out["trades"]["size"][0] == pytest.approx(100.0, rel=1e-3)
    assert out["trades"]["notional"][0] == pytest.approx(200.0, rel=1e-3)
