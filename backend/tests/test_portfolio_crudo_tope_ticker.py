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
def test_cangrejo_b_recorta_la_entrada_en_el_crudo():
    """Corrida por capital con cangrejo B al 1 %: con 10.000 $ y un stop a 1 $
    de distancia, la entrada no puede pasar de 100 acciones aunque el 5 % del
    capital pida 250 (5 % de 10.000 = 500 $ / 2 $)."""
    r = _run("s1", "AAA", "04:10", "04:30", 500, entry=2.0, exitp=1.9, stop=3.0)
    r["backtest_params"].update({"size_by_sl": False, "cangrejo_active": True, "cangrejo_max_loss_at_sl_pct": 1.0})
    out = plr.simulate([r], {"capital": 10000.0, "cap_mode": "skip",
                             "default_exec": {"sizing": "auto", "size_value": 5.0, "size_unit": "pct"}})
    assert out["trades"]["size"][0] == pytest.approx(100.0, rel=1e-6)
    assert out["per_strategy"][0]["cap_report"]["reglas"] == 1
    assert out["per_strategy"][0]["reglas"]["cangrejo_b"] is True
    # Sin la regla, las 250 acciones.
    r2 = _run("s1", "AAA", "04:10", "04:30", 500, entry=2.0, exitp=1.9, stop=3.0)
    r2["backtest_params"]["size_by_sl"] = False
    out2 = plr.simulate([r2], {"capital": 10000.0, "cap_mode": "skip",
                               "default_exec": {"sizing": "auto", "size_value": 5.0, "size_unit": "pct"}})
    assert out2["trades"]["size"][0] == pytest.approx(250.0, rel=1e-6)
    assert out2["per_strategy"][0]["cap_report"]["reglas"] == 0


def test_techo_hibrido_y_tope_de_caja_en_el_crudo():
    """Hibrido (por SL): con 10.000 $, cisne del 500 % y perdida maxima del
    50 %, la posicion no pasa de 1.000 $ de valor (500 acciones a 2 $) aunque
    el riesgo pida mas. Y el tope de caja: nunca mas nocional que la cuenta."""
    r = _run("s1", "AAA", "04:10", "04:30", 500, entry=2.0, exitp=1.9, stop=2.1)
    r["backtest_params"].update({"size_by_sl": True, "hybrid_stop": True, "hybrid_black_swan_pct": 500.0, "hybrid_max_loss_pct": 50.0})
    # 10 % de riesgo con stop a 0,10 $ pediria 10.000 acciones (20.000 $ de nocional).
    out = plr.simulate([r], {"capital": 10000.0, "cap_mode": "skip",
                             "default_exec": {"sizing": "auto", "size_value": 10.0, "size_unit": "pct"}})
    assert out["trades"]["size"][0] == pytest.approx(500.0, rel=1e-6)
    assert out["per_strategy"][0]["cap_report"]["reglas"] == 1
    # Solo tope de caja (sin hibrido): 10.000 $ / 2 $ = 5.000 acciones como maximo.
    r2 = _run("s1", "AAA", "04:10", "04:30", 500, entry=2.0, exitp=1.9, stop=2.1)
    r2["backtest_params"]["size_by_sl"] = True
    out2 = plr.simulate([r2], {"capital": 10000.0, "cap_mode": "skip",
                               "default_exec": {"sizing": "auto", "size_value": 10.0, "size_unit": "pct"}})
    assert out2["trades"]["size"][0] == pytest.approx(5000.0, rel=1e-6)


# ── Los topes van DENTRO del dia: lo saltado no paga locates ni cuenta (19-sep) ──

def test_un_trade_saltado_por_el_tope_no_paga_locates_ni_rompe_la_ruina():
    """Dos cortos a la vez en tickers distintos con tope de exposicion del 5 %:
    el segundo no cabe y se salta. Con locates fijos de la cuenta, el saltado
    NO puede pagar alquiler (antes lo pagaba: 2A perdia 99.273 $ con 478
    trades). Y sin el tope, los dos entran y los dos pagan."""
    runs = [_run("s1", "AAA", "04:10", "04:30", 1000, entry=1.0, exitp=0.9),
            _run("s2", "BBB", "04:15", "04:40", 1000, entry=1.0, exitp=0.9)]
    for r in runs:
        r["backtest_params"]["size_by_sl"] = False
    base = {"capital": 10000.0, "cap_mode": "skip",
            "default_exec": {"sizing": "auto", "size_value": 5.0, "size_unit": "pct"},
            "locates": {"mode": "fixed", "cost": 3.0, "shared": True, "gate": None}}
    con_tope = plr.simulate(runs, dict(base, max_exposure_pct=5.0))
    assert con_tope["cap_report"]["skipped"] == 1
    assert [p["totals"]["n_trades"] for p in con_tope["per_strategy"]] == [1, 0]
    # 5 % de 10.000 = 500 $ a 1 $ = 500 acciones = 5 paquetes x 3 $ = 15 $ solo la primera.
    assert [round(p["totals"]["locates"], 2) for p in con_tope["per_strategy"]] == [15.0, 0.0]
    assert con_tope["per_strategy"][1]["totals"]["pnl_net"] == 0.0
    sin_tope = plr.simulate(runs, dict(base, max_exposure_pct=0.0))
    assert [p["totals"]["n_trades"] for p in sin_tope["per_strategy"]] == [1, 1]
    assert [round(p["totals"]["locates"], 2) for p in sin_tope["per_strategy"]] == [15.0, 15.0]


def test_la_ruina_para_la_cuenta_tambien_con_topes():
    """Un trade que pierde mas que la cuenta la deja a cero y no se opera mas,
    con o sin tope (antes, con tope, la curva recompuesta seguia por debajo de
    cero: la suma de Jaume pasaba de -16.000 $ con 10.000 $ de capital)."""
    import copy
    r = _run("s1", "AAA", "04:10", "04:30", 1000, entry=1.0, exitp=3.0, stop=1.1)   # corto que pierde 200 %
    r["backtest_params"]["size_by_sl"] = False
    r2 = copy.deepcopy(r); r2["trades"][0]["date"] = "2026-01-05"; r2["trades"][0]["entry_time"] = "2026-01-05 04:10:00"; r2["trades"][0]["exit_time"] = "2026-01-05 04:30:00"
    r["trades"].append(r2["trades"][0])
    for cap in (0.0, 80.0):
        out = plr.simulate([r], {"capital": 10000.0, "cap_mode": "skip", "max_exposure_pct": cap,
                                  "default_exec": {"sizing": "auto", "size_value": 60.0, "size_unit": "pct"}})
        assert out["ruined"] is True
        assert min(out["equity"]) >= 0.0
        assert out["per_strategy"][0]["totals"]["n_trades"] == 1


# ── Los dos modos de Kelly de Jaume (20-sep) ────────────────────────────
