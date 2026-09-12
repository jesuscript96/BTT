"""Escalera del scalping «complejo» (2026-09-12).

  1. REGLA Nº1: `ladder=None` (lo normal) no cambia ni un trade; el modo
     «simple» compila sin escalera; una escalera que no hace nada es None.
  2. Los cálculos puros: parse, precio de nivel, qué lado se visita primero,
     nivel tocado, cantidades en $ y en %.
  3. El simulador con la escalera del ejemplo de Jaume (largo a 10 $, paso
     1 %, en contra añade, a favor quita): añadidos con precio medio, quitas
     como legs «Escalera», suelo (core), techo (tope), recorrido, opción A
     (cada nivel una vez) frente a B (rearmar), vaciado y siguiente scalp, y
     que el stop en % se mide sobre el precio medio.
  4. `sim_dispatch` desvía del JIT y `run_backtest` entero por el secuencial.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import sim_dispatch
from app.services.escalera import (
    ConfigEscalera, a_acciones, nivel_precio, nivel_tocado, orden_lados, parse_escalera,
)
from app.services.portfolio_sim import simulate
from app.services.strategy_engine import compile_strategy_def, translate_strategy


def _cfg(**kw):
    base = dict(step_pct=1.0, favor_action="reduce", favor_amount=50.0, favor_unit="pct",
                contra_action="add", contra_amount=50.0, contra_unit="pct",
                core_amount=0.0, core_unit="pct", cap_amount=300.0, cap_unit="pct",
                max_travel_pct=5.0, rearm=False)
    base.update(kw)
    return ConfigEscalera(**base)


# ── 1. Regla nº1 ───────────────────────────────────────────────────────────

def _kw_base():
    n = 12
    close = np.array([10.0, 10.0, 10.0, 9.9, 9.8, 9.9, 10.0, 10.1, 10.2, 10.1, 10.0, 10.0])
    return dict(close=close, open_=close.copy(), high=close + 0.02, low=close - 0.02,
                entries=np.array([0, 1] + [0] * 10, dtype=bool), exits=np.zeros(n, dtype=bool),
                direction="longonly", init_cash=100000.0, risk_r=1000.0, risk_type="FIXED",
                sl_stop=0.30, tp_stop=0.50)


class TestReglaNumeroUno:
    def test_ladder_none_no_cambia_nada(self):
        a = simulate(**_kw_base())
        b = simulate(**_kw_base(), ladder=None)
        assert a["trades"] == b["trades"]
        assert np.array_equal(a["equity"], b["equity"])
        assert all("escalera_executions" not in t for t in a["trades"])

    def test_modo_simple_compila_sin_escalera(self):
        d = {"bias": "long",
             "entry_logic": {"timeframe": "1m", "root_condition": {"type": "group", "operator": "AND", "conditions": [
                 {"type": "indicator_comparison", "source": {"name": "Bar Close", "offset": 0},
                  "comparator": "GREATER_THAN", "target": 0.0, "timeframe": "1m"}]}},
             "exit_logic": {"timeframe": "1m", "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
             "risk_management": {"use_hard_stop": False},
             "scalping": {"timeframe": "1m", "mode": "simple",
                          "root_condition": {"type": "group", "operator": "AND", "conditions": [
                              {"type": "indicator_comparison", "source": {"name": "Bar Close", "offset": 0},
                               "comparator": "GREATER_THAN", "target": 0.0, "timeframe": "1m"}]},
                          "ladder": {"step_pct": 1, "favor_action": "reduce", "favor_amount": 50}}}
        c = compile_strategy_def(d)
        assert c["scalping"]["ladder"] is None
        d["scalping"]["mode"] = "complex"
        c2 = compile_strategy_def(d)
        assert isinstance(c2["scalping"]["ladder"], ConfigEscalera)

    def test_escalera_que_no_hace_nada_es_none(self):
        assert parse_escalera(None) is None
        assert parse_escalera({}) is None
        assert parse_escalera({"step_pct": 0, "favor_action": "reduce", "favor_amount": 10}) is None
        assert parse_escalera({"step_pct": 1, "favor_action": "none", "contra_action": "none"}) is None
        assert parse_escalera({"step_pct": 1, "favor_action": "reduce", "favor_amount": 0}) is None


# ── 2. Cálculos puros ──────────────────────────────────────────────────────

class TestPuros:
    def test_parse_normaliza(self):
        c = parse_escalera({"step_pct": "2", "favor_action": "quitar", "favor_amount": 25, "favor_unit": "$",
                            "contra_action": "añadir", "contra_amount": 100, "contra_unit": "pct",
                            "core_amount": 10, "core_unit": "usd", "cap_amount": 0, "max_travel_pct": 6,
                            "rearm": True})
        assert c.step_pct == 2 and c.favor_action == "reduce" and c.favor_unit == "usd"
        assert c.contra_action == "add" and c.contra_unit == "pct"
        assert c.core_amount == 10 and c.core_unit == "usd" and c.cap_amount == 0
        assert c.max_k == 3 and c.rearm is True

    def test_nivel_precio(self):
        assert nivel_precio(10.0, True, 2, 1.0) == pytest.approx(10.2)
        assert nivel_precio(10.0, True, -3, 1.0) == pytest.approx(9.7)
        # En corto, «a favor» es hacia abajo.
        assert nivel_precio(10.0, False, 2, 1.0) == pytest.approx(9.8)

    def test_orden_lados(self):
        assert orden_lados(10.0, 10.5, True) == ("contra", "favor")
        assert orden_lados(10.0, 9.5, True) == ("favor", "contra")
        assert orden_lados(10.0, 10.5, False) == ("favor", "contra")

    def test_nivel_tocado(self):
        assert nivel_tocado("favor", True, 10.1, high=10.15, low=9.9)
        assert not nivel_tocado("favor", True, 10.2, high=10.15, low=9.9)
        assert nivel_tocado("contra", True, 9.9, high=10.15, low=9.9)
        assert nivel_tocado("favor", False, 9.9, high=10.15, low=9.9)

    def test_a_acciones(self):
        assert a_acciones(50, "pct", 100, 9.9) == 50
        assert a_acciones(99, "usd", 100, 9.9) == pytest.approx(10)
        assert a_acciones(0, "pct", 100, 9.9) == 0


# ── 3. El simulador ────────────────────────────────────────────────────────

def _camino(closes, entry_bar=1):
    """Velas planas (open=high=low=close) salvo un margen de 1 centavo, para
    saber exactamente qué nivel toca cada vela."""
    c = np.asarray(closes, dtype=float)
    n = len(c)
    entries = np.zeros(n, dtype=bool); entries[entry_bar - 1] = True   # fill en entry_bar
    return dict(close=c, open_=c.copy(), high=c + 0.001, low=c - 0.001,
                entries=entries, exits=np.zeros(n, dtype=bool),
                direction="longonly", init_cash=1_000_000.0, risk_r=1000.0, risk_type="FIXED",
                sl_stop=0.30, tp_stop=0.50)


class TestSimulador:
    def test_ejemplo_de_jaume(self):
        # Entra 100 acc. a 10 (1000 $ / 10). Baja 1 % y 2 % → añade 50 y 50
        # (200). Sube 3 pasos (9.9, 10.0, 10.1) → quita 50, 50 y 50 → 50; el
        # cuarto paso (10.2) quita los 50 que quedan y vacía el scalp (core 0).
        kw = _camino([10, 10, 10, 9.9, 9.8, 9.9, 10.0, 10.1, 10.2, 10.2])
        res = simulate(**kw, ladder=_cfg())
        legs = [t for t in res["trades"] if t["exit_reason"] == "Escalera"]
        assert [round(t["size"]) for t in legs] == [50, 50, 50, 50]
        assert [t["exit_idx"] for t in legs] == [5, 6, 7, 8]
        assert not [t for t in res["trades"] if t["exit_reason"] != "Escalera"]   # vaciado: sin cierre EOD
        ex = legs[-1]["escalera_executions"]
        assert [e["kind"] for e in ex] == ["add", "add", "reduce", "reduce", "reduce", "reduce"]
        assert [e["nivel"] for e in ex] == [-1, -2, -1, 0, 1, 2]
        # Precio medio tras los dos añadidos: (100·10 + 50·9.9 + 50·9.8)/200.
        assert ex[1]["avg_entry_price"] == pytest.approx((1000 + 495 + 490) / 200, rel=1e-6)
        assert [round(e["position_size"]) for e in ex] == [150, 200, 150, 100, 50, 0]

    def test_opcion_a_no_repite_nivel_y_b_si(self):
        # Baja a 9.9 (añade), vuelve a 10 (quita), baja otra vez a 9.9.
        kw = _camino([10, 10, 10, 9.9, 10.0, 9.9, 10.0, 10.0])
        a = simulate(**kw, ladder=_cfg(rearm=False))
        b = simulate(**kw, ladder=_cfg(rearm=True))
        ex_a = [e for t in a["trades"] for e in t.get("escalera_executions", [])]
        ex_b = [e for t in b["trades"] for e in t.get("escalera_executions", [])]
        # A: cada (nivel, dirección) una vez: añade en -1 bajando, quita en 0
        # subiendo, y la segunda bajada/subida ya no opera.
        assert [(e["kind"], e["nivel"]) for e in ex_a] == [("add", -1), ("reduce", 0)]
        # B: cada cruce opera.
        assert [(e["kind"], e["nivel"]) for e in ex_b] == [("add", -1), ("reduce", 0), ("add", -1), ("reduce", 0)]

    def test_core_es_el_suelo(self):
        # Solo quita a favor; core 40 % de la inicial → de 100 baja a 50 y luego
        # solo hasta 40, y ahí se queda.
        kw = _camino([10, 10, 10, 10.1, 10.2, 10.3, 10.3])
        res = simulate(**kw, ladder=_cfg(contra_action="none", core_amount=40))
        legs = [t for t in res["trades"] if t["exit_reason"] == "Escalera"]
        assert [round(t["size"]) for t in legs] == [50, 10]
        final = [t for t in res["trades"] if t["exit_reason"] != "Escalera"][0]
        assert round(final["size"]) == 40

    def test_core_cero_vacia_y_el_siguiente_gatillo_reentra(self):
        kw = _camino([10, 10, 10, 10.1, 10.2, 10.2, 10.2, 10.2, 10.2])
        kw["entries"][5] = True          # nuevo gatillo tras el vaciado
        kw["accumulate"] = True; kw["max_reentries"] = -1
        res = simulate(**kw, ladder=_cfg(contra_action="none"))
        legs = [t for t in res["trades"] if t["exit_reason"] == "Escalera"]
        assert [round(t["size"]) for t in legs] == [50, 50]
        assert "escalera_executions" in legs[-1]      # la bitácora cuelga de la leg que vació
        # Reentrada: un trade nuevo que empieza en la vela 6 y cierra a EOD.
        otros = [t for t in res["trades"] if t["exit_reason"] != "Escalera"]
        assert len(otros) == 1 and otros[0]["entry_idx"] == 6

    def test_tope_es_el_techo_y_recorrido_manda(self):
        # Solo añade en contra, 100 % de la inicial por paso, techo 250 %,
        # recorrido 3 %: a 9.9 → 200, a 9.8 → 250 (recortado), a 9.7 → nada
        # (techo), a 9.6 → fuera del recorrido, nada.
        kw = _camino([10, 10, 10, 9.9, 9.8, 9.7, 9.6, 9.6])
        res = simulate(**kw, ladder=_cfg(favor_action="none", contra_amount=100, cap_amount=250, max_travel_pct=3))
        final = res["trades"][-1]
        ex = final["escalera_executions"]
        assert [round(e["position_size"]) for e in ex] == [200, 250]
        assert round(final["size"]) == 250

    def test_cantidades_en_dolares(self):
        # Añade 990 $ a 9.9 → 100 acciones más.
        kw = _camino([10, 10, 10, 9.9, 9.9])
        res = simulate(**kw, ladder=_cfg(favor_action="none", contra_amount=990, contra_unit="usd"))
        ex = res["trades"][-1]["escalera_executions"]
        assert round(ex[0]["size"]) == 100

    def test_stop_en_porcentaje_sobre_el_precio_medio(self):
        # Stop 2 %. Entra a 10 (stop 9.80). Baja a 9.9 → añade 100 % → medio
        # 9.95 → stop 9.751. Una vela a 9.78 NO salta (antes sí habría saltado).
        kw = _camino([10, 10, 10, 9.9, 9.78, 9.78])
        kw["sl_stop"] = 0.02
        res = simulate(**kw, ladder=_cfg(favor_action="none", contra_amount=100))
        assert res["trades"][-1]["exit_reason"] == "EOD"
        # Y a 9.74 sí salta.
        kw2 = _camino([10, 10, 10, 9.9, 9.74, 9.74]); kw2["sl_stop"] = 0.02
        res2 = simulate(**kw2, ladder=_cfg(favor_action="none", contra_amount=100))
        assert res2["trades"][-1]["exit_reason"] == "SL"

    def test_corto_simetrico(self):
        # En corto, «a favor» es hacia abajo: baja 1 % → quita 50.
        kw = _camino([10, 10, 10, 9.9, 9.9]); kw["direction"] = "shortonly"
        res = simulate(**kw, ladder=_cfg(contra_action="none"))
        legs = [t for t in res["trades"] if t["exit_reason"] == "Escalera"]
        assert len(legs) == 1 and round(legs[0]["size"]) == 50 and legs[0]["pnl"] > 0

    def test_la_salida_principal_cierra_todo(self):
        # Añade dos veces y luego la salida por señal cierra las 200.
        kw = _camino([10, 10, 10, 9.9, 9.8, 9.8, 9.8, 9.8])
        kw["exits"][5] = True
        res = simulate(**kw, ladder=_cfg(favor_action="none"))
        final = res["trades"][-1]
        assert final["exit_reason"] == "Signal" and round(final["size"]) == 200


# ── 4. Dispatch y run_backtest ─────────────────────────────────────────────

def test_dispatch_desvia_del_jit(monkeypatch):
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    kw = _camino([10, 10, 10, 9.9, 9.8, 9.9, 10.0, 10.1, 10.2, 10.2])
    assert sim_dispatch.simulate(**kw, ladder=_cfg())["trades"] == simulate(**kw, ladder=_cfg())["trades"]
    # Con None el kwarg se retira y el kernel no lo ve.
    assert len(sim_dispatch.simulate(**kw, ladder=None)["trades"]) == 1


def _dia(ticker, date, n=120):
    ts = pd.date_range(f"{date} 09:30", periods=n, freq="1min")
    pasos = np.where(np.arange(n) % 4 == 3, -0.01, 0.01)
    close = 1.0 + np.cumsum(pasos)
    return pd.DataFrame({"ticker": ticker, "date": date, "timestamp": ts,
                         "open": close, "high": close + 0.002, "low": close - 0.002, "close": close,
                         "volume": np.full(n, 100000.0)})


def test_run_backtest_complejo(monkeypatch):
    from app.services.backtest_service import run_backtest
    monkeypatch.delenv("BTT_SLAB_STREAM_ENABLED", raising=False)
    monkeypatch.delenv("BACKTEST_PARALLEL_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "0")
    cond = lambda umbral: {"type": "indicator_comparison", "source": {"name": "Bar Close", "offset": 0},
                           "comparator": "GREATER_THAN", "target": float(umbral), "timeframe": "1m"}
    verde = {"type": "indicator_comparison", "source": {"name": "Bar Close", "offset": 0},
             "comparator": "GREATER_THAN", "target": {"name": "Bar Close", "offset": 1}, "timeframe": "1m"}
    base = {"bias": "long",
            "entry_logic": {"timeframe": "1m", "root_condition": {"type": "group", "operator": "AND", "conditions": [cond(1.05)]}},
            "exit_logic": {"timeframe": "1m", "root_condition": {"type": "group", "operator": "AND", "conditions": [cond(1.30)]}},
            "risk_management": {"size_by_sl": False, "use_hard_stop": True,
                                "hard_stop": {"type": "Percentage", "value": 50},
                                "use_take_profit": True, "take_profit_mode": "Full",
                                "take_profit": {"type": "Time", "value": 30}},
            "scalping": {"timeframe": "1m", "root_condition": {"type": "group", "operator": "AND", "conditions": [verde]},
                         "max_minutes": 6, "cooldown_bars": 0, "capital_pct": 100, "mode": "simple"}}
    dias = [_dia("AAA", "2026-09-10")]
    qual = pd.DataFrame([{"ticker": "AAA", "date": "2026-09-10", "prev_close": 1.0, "gap_pct": 50.0}])

    def run(sdef):
        return run_backtest(qualifying_df=qual, strategy_def=sdef, init_cash=10000.0, risk_r=100.0,
                            risk_type="FIXED", market_sessions=["rth"],
                            day_group_iter=(((d["date"].iloc[0], d["ticker"].iloc[0]), d) for d in dias),
                            n_groups_hint=1)

    simple = run(base)
    complejo = dict(base, scalping=dict(base["scalping"], mode="complex", ladder={
        "step_pct": 0.5, "favor_action": "none", "favor_amount": 0,
        "contra_action": "add", "contra_amount": 50, "contra_unit": "pct",
        "core_amount": 0, "cap_amount": 0, "max_travel_pct": 5, "rearm": False}))
    res = run(complejo)
    assert len(simple["trades"]) > 0 and len(res["trades"]) > 0
    # Con la escalera hay trades con añadidos registrados; en simple, ninguno.
    assert any(t.get("escalera_executions") for t in res["trades"])
    assert not any(t.get("escalera_executions") for t in simple["trades"])
    # Y el detalle para el gráfico (`executions`) lleva los de la escalera
    # marcados, para pintarlos pequeños.
    ex_esc = [e for t in res["trades"] for e in (t.get("executions") or []) if e.get("escalera")]
    assert ex_esc and all(e["kind"] in ("add", "reduce") and "Escalera" in e["label"] for e in ex_esc)
    assert not any(e.get("escalera") for t in simple["trades"] for e in (t.get("executions") or []))
