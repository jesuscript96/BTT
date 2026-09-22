"""TP POR LOTE en piramidación (PRD 2026-09-22, docs/PRD_TP_POR_LOTE_20260922.md).

La matemática EXACTA que el PRD manda, vela a vela, sobre el mismo harness
de `test_lot_stop_sim.py` (corto a 10 $, base 10 acciones, add de 100 $ =
10 acciones, sin fees ni slippage para que cada leg dé números redondos):

  §6.1 regla nº1 ............ cubierta por los dorados de lot_stop/pyramid
                              (una definición sin lot_tp no cambia NADA) +
                              test de compilador sin la clave
  §6.2 escalera a mano ...... rungs 50 % a +5 % y 30 % a +10 %, con SU
                              precio, SU tamaño y el resto al cierre global;
                              variante "una vela cruza DOS rungs" (toque y
                              gap por open)
  §6.3 SL inamovible ........ +9 % recorrido y vuelta a perforar → cero
                              rungs; empate en la misma vela → gana el stop
  §6.4 rung único ........... doble toque del nivel → una sola leg
  §6.5 recorte de caja ...... add de 2 $ recortado a 1 $ → rung del 50 %
                              cierra EXACTAMENTE 0,05 $ de acción
  §6.6 vela de entrada ...... el rung no dispara en la vela en que entra el add
  §6.7 Σ = 100 % ............ el lote muere limpio y el trade sigue
  §6.8 fusión ............... las legs llevan la identidad del trade
  §6.9 round-trip ........... schema valida fuerte (422) y compile adjunta
                              el bloque canónico solo al nivel que lo declara
"""
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.schemas.strategy import StrategyCreate
from app.services.portfolio_sim import simulate
from app.services.strategy_engine import (
    compile_strategy_def, normaliza_lot_tp, translate_strategy,
)

RISK = 100.0      # FIXED: 100 $ por trade → 10 acciones a 10 $
CASH = 10000.0
N = 20


def _dia(n=N, precio=10.0, lows_puntual=None, highs_puntual=None, opens_puntual=None):
    open_ = np.full(n, precio)
    close = np.full(n, precio)
    high = np.full(n, precio + 0.05)
    low = np.full(n, precio - 0.05)
    for i, v in (lows_puntual or {}).items():
        low[i] = v
    for i, v in (highs_puntual or {}).items():
        high[i] = v
    for i, v in (opens_puntual or {}).items():
        open_[i] = v
    ts = pd.date_range("2026-09-22 04:00", periods=n, freq="1min")
    ts_ns = ts.values.astype("datetime64[ns]").astype(np.int64)
    return open_, high, low, close, ts_ns


def _senal(*barras, n=N):
    s = np.zeros(n, dtype=bool)
    for b in barras:
        s[b] = True
    return s


def _nivel_add(senal, lot_stop=None, lot_tp=None, **kw):
    nv = {
        "signals": senal, "action": "add", "capital_frac": 0.0,
        "max_fires": kw.pop("max_fires", 2), "unit": "usd",
        "amount_usd": kw.pop("amount_usd", 100.0), "size_by_sl": False,
        "hybrid_stop": False, "hybrid_black_swan_pct": None,
        "hybrid_max_loss_pct": None,
    }
    if lot_stop is not None:
        nv["lot_stop"] = lot_stop
    if lot_tp is not None:
        nv["lot_tp"] = lot_tp
    nv.update(kw)
    return nv


def _correr(open_, high, low, close, ts_ns, entries, exits, niveles,
            direction="shortonly", **kw):
    hods = np.maximum.accumulate(high)
    lods = np.minimum.accumulate(low)
    prev_h = np.empty_like(hods); prev_h[0] = high[0]; prev_h[1:] = hods[:-1]
    prev_l = np.empty_like(lods); prev_l[0] = low[0]; prev_l[1:] = lods[:-1]
    params = dict(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction=direction,
        init_cash=CASH, risk_r=RISK, risk_type="FIXED",
        fees=0.0, fee_type="PERCENT", slippage=0.0,
        look_ahead_prevention=True,
        pyramid_levels=niveles, pyramid_sequential=False,
        timestamps=ts_ns,
        hods=hods, lods=lods, prev_highs=prev_h, prev_lows=prev_l,
    )
    params.update(kw)
    return simulate(**params)


def _tp_legs(res):
    return [t for t in res["trades"] if str(t["exit_reason"]).startswith("Lot TP")]


# ── §6.2: la escalera, a mano ──────────────────────────────────────────────

def test_escalera_a_mano_50_y_30_con_resto_al_cierre_global():
    """Corto: base 10 acc a 10 $ + lote de 10 acc (fill bar 5). Rungs: 50 % a
    +5 % (nivel 9,50) y 30 % a +10 % (nivel 9,00). Barra 6 toca 9,40 → leg de
    5 acc a 9,50 (pnl +2,5). Barra 8 toca 8,90 → leg de 3 acc a 9,00 (pnl +3).
    El RESTO (2 acc) y la base salen con la salida global (pnl 0 al precio de
    entrada)."""
    open_, high, low, close, ts = _dia(lows_puntual={6: 9.4, 8: 8.9})
    niveles = [_nivel_add(_senal(4), lot_tp={"rungs": [(5.0, 50.0), (10.0, 30.0)]})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    legs = _tp_legs(res)
    assert len(legs) == 2
    l1, l2 = legs
    assert l1["exit_reason"] == "Lot TP (1/2)"
    assert l1["exit_idx"] == 6 and l1["entry_price"] == 10.0
    assert round(l1["size"], 6) == 5.0 and round(l1["pnl"], 4) == 2.5
    assert l2["exit_reason"] == "Lot TP (2/2)"
    assert l2["exit_idx"] == 8
    assert round(l2["size"], 6) == 3.0 and round(l2["pnl"], 4) == 3.0
    # el resto del lote (2 acc) viaja con la base hasta la salida global
    final = [t for t in res["trades"] if not str(t["exit_reason"]).startswith("Lot TP")]
    assert any(round(t["size"], 6) == 12.0 for t in final), \
        f"el resto del lote no salió con el trade: {[t['size'] for t in final]}"
    # §6.8: identidad del trade en cada leg (patrón PRD_FIX_SL_LOTE_FUSION)
    for l in legs:
        assert l["trade_entry_price"] == 10.0
        assert "trade_stop_loss" in l


def test_una_vela_cruza_dos_rungs_por_toque():
    """§6.2 variante: una sola vela toca 9,50 y 9,00 → las DOS legs en esa
    vela, en travel ascendente, cada una a SU nivel."""
    open_, high, low, close, ts = _dia(lows_puntual={6: 8.9})
    niveles = [_nivel_add(_senal(4), lot_tp={"rungs": [(5.0, 50.0), (10.0, 30.0)]})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    legs = _tp_legs(res)
    assert len(legs) == 2
    assert legs[0]["exit_idx"] == legs[1]["exit_idx"] == 6
    assert round(legs[0]["exit_price"], 6) == 9.5   # SU nivel, no el low
    assert round(legs[1]["exit_price"], 6) == 9.0
    assert round(legs[0]["pnl"], 4) == 2.5 and round(legs[1]["pnl"], 4) == 3.0


def test_una_vela_cruza_dos_rungs_por_gap_de_apertura():
    """§6.2 variante gap: la vela ABRE en 8,80 (ya más allá de los dos
    niveles) → AMBAS legs al precio del open (semántica límite, §4.2)."""
    open_, high, low, close, ts = _dia(opens_puntual={6: 8.8}, lows_puntual={6: 8.8})
    niveles = [_nivel_add(_senal(4), lot_tp={"rungs": [(5.0, 50.0), (10.0, 30.0)]})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    legs = _tp_legs(res)
    assert len(legs) == 2
    assert round(legs[0]["exit_price"], 6) == 8.8
    assert round(legs[1]["exit_price"], 6) == 8.8
    assert round(legs[0]["pnl"], 4) == round((10 - 8.8) * 5, 4)
    assert round(legs[1]["pnl"], 4) == round((10 - 8.8) * 3, 4)


# ── §6.3: el SL del lote es inamovible ─────────────────────────────────────

def test_recorrido_casi_completo_y_vuelta_al_cinturon_cero_rungs():
    """El lote recorre +4 % (rung al +5 % no disparado) y vuelve a perforar su
    cinturón → leg única de Pyramid Lot Stop por el lote entero."""
    open_, high, low, close, ts = _dia(lows_puntual={6: 9.61}, highs_puntual={7: 10.6})
    niveles = [_nivel_add(_senal(4), lot_stop={"mode": "pct", "pct": 5.0},
                          lot_tp={"rungs": [(5.0, 50.0)]})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    assert _tp_legs(res) == []
    ls = [t for t in res["trades"] if t["exit_reason"] == "Pyramid Lot Stop"]
    assert len(ls) == 1 and round(ls[0]["size"], 6) == 10.0


def test_empate_en_la_misma_vela_gana_el_stop():
    """§4.3: la vela toca el cinturón (10,5) Y el rung (9,5) → gana el stop;
    no hay legs de Lot TP y el lote cierra entero por el cinturón."""
    open_, high, low, close, ts = _dia(lows_puntual={6: 9.4}, highs_puntual={6: 10.6})
    niveles = [_nivel_add(_senal(4), lot_stop={"mode": "pct", "pct": 5.0},
                          lot_tp={"rungs": [(5.0, 50.0)]})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    assert _tp_legs(res) == []
    ls = [t for t in res["trades"] if t["exit_reason"] == "Pyramid Lot Stop"]
    assert len(ls) == 1 and round(ls[0]["pnl"], 4) == -5.0  # (10−10,5)×10


# ── §6.4: un rung dispara UNA vez por lote ─────────────────────────────────

def test_rung_no_se_rearma_con_el_segundo_toque():
    open_, high, low, close, ts = _dia(lows_puntual={6: 9.4, 8: 9.4})
    niveles = [_nivel_add(_senal(4), lot_tp={"rungs": [(5.0, 50.0)]})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    legs = _tp_legs(res)
    assert len(legs) == 1 and legs[0]["exit_idx"] == 6


# ── §6.5: recorte de caja, número exacto ───────────────────────────────────

def test_rungs_sobre_el_tamano_ejecutado_del_add():
    """El add PIDE 2 $ pero la caja (101 $ con 100 comprometidos) solo deja
    ejecutar 1 $ = 0,10 acciones. Un rung del 50 % cierra EXACTAMENTE 0,05
    acciones («% del original» = % del tamaño EJECUTADO del add)."""
    open_, high, low, close, ts = _dia(lows_puntual={6: 9.4})
    niveles = [_nivel_add(_senal(4), amount_usd=2.0, lot_tp={"rungs": [(5.0, 50.0)]})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12),
                  niveles, init_cash=101.0)

    legs = _tp_legs(res)
    assert len(legs) == 1
    assert round(legs[0]["size"], 4) == 0.05
    assert round(legs[0]["pnl"], 4) == round((10 - 9.5) * 0.05, 4)
    # el add quedó anotado como recortado por caja
    add_exec = [e for t in res["trades"] for e in (t.get("pyr_executions") or [])
                if e["kind"] == "add"]
    assert add_exec and add_exec[0].get("recortado_por_caja") == 2.0


# ── §6.6: nunca en la vela de entrada del add ──────────────────────────────

def test_rung_no_dispara_en_la_vela_de_fill_del_add():
    """El add llena en la barra 5 (señal en la 4) y ESA barra toca el nivel:
    por PRD §4.4 el rung no dispara en la vela de fill — dispara desde la 6.
    (El cinturón sí puede saltar en la de fill: asimetría deliberada.)"""
    open_, high, low, close, ts = _dia(lows_puntual={5: 9.4, 6: 9.4})
    niveles = [_nivel_add(_senal(4), lot_tp={"rungs": [(5.0, 50.0)]})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    legs = _tp_legs(res)
    assert len(legs) == 1 and legs[0]["exit_idx"] == 6


# ── §6.7: Σ = 100 % → el lote muere limpio, el trade sigue ─────────────────

def test_lote_vacio_por_rungs_el_trade_sigue_con_la_base():
    open_, high, low, close, ts = _dia(lows_puntual={6: 9.4, 8: 8.9})
    niveles = [_nivel_add(_senal(4), lot_tp={"rungs": [(5.0, 50.0), (10.0, 50.0)]})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    legs = _tp_legs(res)
    assert len(legs) == 2
    assert round(sum(l["size"] for l in legs), 6) == 10.0   # el lote entero
    # la base (10 acc) sigue viva y sale con la salida global
    final = [t for t in res["trades"] if not str(t["exit_reason"]).startswith("Lot TP")]
    assert any(round(t["size"], 6) == 10.0 for t in final)


# ── §6.9: normalización, schema (422) y compilador ─────────────────────────

@pytest.mark.parametrize("bloque, motivo", [
    ("no-dict", "debe ser un objeto"),
    ({}, "rungs"),
    ({"rungs": []}, "no vacía"),
    ({"rungs": [{"travel_pct": 0, "capital_pct": 50}]}, "travel_pct debe ser > 0"),
    ({"rungs": [{"travel_pct": -5, "capital_pct": 50}]}, "travel_pct debe ser > 0"),
    ({"rungs": [{"travel_pct": 5, "capital_pct": 0}]}, "capital_pct"),
    ({"rungs": [{"travel_pct": 5, "capital_pct": 101}]}, "capital_pct"),
    ({"rungs": [{"travel_pct": 10, "capital_pct": 50},
                {"travel_pct": 10, "capital_pct": 30}]}, "ESTRICTAMENTE"),
    ({"rungs": [{"travel_pct": 20, "capital_pct": 50},
                {"travel_pct": 10, "capital_pct": 30}]}, "ESTRICTAMENTE"),
    ({"rungs": [{"travel_pct": 5, "capital_pct": 60},
                {"travel_pct": 10, "capital_pct": 60}]}, "no puede pasar de 100"),
])
def test_normaliza_rechaza_imposibles(bloque, motivo):
    with pytest.raises(ValueError, match=motivo):
        normaliza_lot_tp(bloque)


def test_normaliza_canonico_y_coerciones():
    out = normaliza_lot_tp({"rungs": [
        {"travel_pct": "5", "capital_pct": 50.0},
        {"travel_pct": 10, "capital_pct": 30}]})
    assert out == {"rungs": [(5.0, 50.0), (10.0, 30.0)]}


def _def_con_piramide(lot_tp=None, action="add"):
    si = {"type": "group", "operator": "AND", "conditions": [
        {"type": "indicator_comparison", "source": {"name": "Bar Close"},
         "comparator": "GREATER_THAN", "target": 0.0, "timeframe": "1m"}]}
    nivel = {"times": 2, "root_condition": si, "action": action,
             "unit": "usd", "capital_pct": 100}
    if lot_tp is not None:
        nivel["lot_tp"] = lot_tp
    return {"name": "test tp por lote", "bias": "short",
            "entry_logic": {"timeframe": "1m", "root_condition": si},
            "exit_logic": {"timeframe": "1m",
                           "root_condition": {"type": "group", "operator": "AND",
                                              "conditions": []}},
            "risk_management": {"use_hard_stop": True,
                                "hard_stop": {"type": "Percentage", "value": 10.0}},
            "pyramiding": {"timeframe": "1m", "mode": "individual",
                           "levels": [nivel]}}


def test_schema_acepta_lot_tp_valido_y_rechaza_basura_con_422():
    ok = _def_con_piramide({"rungs": [{"travel_pct": 5, "capital_pct": 50}]})
    StrategyCreate(**ok)   # no raise

    for malo in ({"rungs": []},
                 {"rungs": [{"travel_pct": 5, "capital_pct": 50},
                            {"travel_pct": 5, "capital_pct": 30}]},
                 {"rungs": [{"travel_pct": 5, "capital_pct": 60},
                            {"travel_pct": 10, "capital_pct": 60}]}):
        with pytest.raises(ValidationError):
            StrategyCreate(**_def_con_piramide(malo))


def test_schema_rechaza_lot_tp_en_nivel_reduce():
    red = {"times": 1, "root_condition": {"type": "group", "operator": "AND",
                                          "conditions": []},
           "action": "reduce", "unit": "pct", "capital_pct": 10,
           "lot_tp": {"rungs": [{"travel_pct": 5, "capital_pct": 50}]}}
    d = _def_con_piramide()
    d["pyramiding"]["levels"] = [red]
    with pytest.raises(ValidationError):
        StrategyCreate(**d)


def test_compilador_adjunta_lot_tp_canonico_solo_al_nivel_que_lo_declara():
    d = _def_con_piramide({"rungs": [{"travel_pct": "5", "capital_pct": 50},
                                     {"travel_pct": 10, "capital_pct": 30}]})
    niveles = compile_strategy_def(d)["pyramid_levels_def"]
    assert niveles[0]["lot_tp"] == {"rungs": [(5.0, 50.0), (10.0, 30.0)]}

    # sin la clave → el nivel sale SIN lot_tp (regla nº1: bit-idéntico)
    d2 = _def_con_piramide()
    assert "lot_tp" not in compile_strategy_def(d2)["pyramid_levels_def"][0]


def test_translate_pasa_lot_tp_al_simulador():
    d = _def_con_piramide({"rungs": [{"travel_pct": 5, "capital_pct": 50}]})
    compiled = compile_strategy_def(d)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-09-22 04:00", periods=6, freq="1min"),
        "open": np.full(6, 10.0), "high": np.full(6, 10.05),
        "low": np.full(6, 9.95), "close": np.full(6, 10.0),
        "volume": np.full(6, 1000.0),
    })
    sig = translate_strategy(df, d, {}, compiled=compiled)
    niveles = sig["pyramid_levels"]
    assert niveles and niveles[0].get("lot_tp") == {"rungs": [(5.0, 50.0)]}
