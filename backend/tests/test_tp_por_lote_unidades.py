"""TP POR LOTE: unidad de los peldaños (Jaume 30-sep).

  * sin `unit` ("pct") ... lo de siempre: % del tamaño ejecutado del lote en
                           fracción de acción (bit-idéntico, el canónico sale
                           SIN la clave `unit`).
  * "lot_pct" ............ % del lote en ACCIONES ENTERAS: round(pct × inicial),
                           mínimo 1, tope lo que quede; el peldaño con el que el
                           acumulado llega a 100 cierra el resto
                           (33/33/34 sobre 90 → 30/30/30).
  * "shares" ............. acciones fijas por peldaño, tope lo que quede.

Paridad py ↔ jit: una estrategia piramidada nunca va por el kernel
(`sim_dispatch.simulate` la desvía al Python), así que el dispatcher y el
motor Python deben dar EXACTAMENTE lo mismo con cada unidad.
"""
import pytest

from app.services import sim_dispatch
from app.services.strategy_engine import compile_strategy_def, normaliza_lot_tp

from tests.test_tp_por_lote import _correr, _dia, _nivel_add, _senal, _tp_legs


def _lote_de_90(lot_tp):
    """Corto a 10 $: base 10 acc + lote de 900 $ = 90 acc (fill vela 5).
    Peldaños a +5/+10/+15 % → 9,50 / 9,00 / 8,50, tocados en las velas 6, 8, 10."""
    open_, high, low, close, ts = _dia(lows_puntual={6: 9.4, 8: 8.9, 10: 8.4})
    niveles = [_nivel_add(_senal(4), amount_usd=900.0, max_fires=1, lot_tp=lot_tp)]
    return (open_, high, low, close, ts, _senal(1), _senal(15), niveles)


def _tamanos(res):
    return [round(t["size"], 6) for t in _tp_legs(res)]


def test_lot_pct_33_33_34_sobre_90_da_30_30_30():
    canon = normaliza_lot_tp({"unit": "lot_pct", "rungs": [
        {"travel_pct": 5, "capital_pct": 33}, {"travel_pct": 10, "capital_pct": 33},
        {"travel_pct": 15, "capital_pct": 34}]})
    assert canon["unit"] == "lot_pct"
    res = _correr(*_lote_de_90(canon))
    assert _tamanos(res) == [30.0, 30.0, 30.0]
    execs = [e for t in res["trades"] for e in (t.get("pyr_executions") or []) if e["kind"] == "lot_tp"]
    assert [e["lot_size0"] for e in execs] == [90.0, 90.0, 90.0]
    assert [round(e["lot_frac"], 6) for e in execs] == [round(30 / 90, 6)] * 3
    assert [e["lot_rest"] for e in execs] == [60.0, 30.0, 0.0]


def test_lot_pct_redondea_minimo_1_y_resto_cabalga_si_no_llega_a_100():
    # 1 % de 90 = 0,9 → 1 acción; 50 % → 45; Σ 51 < 100 → el resto cabalga (44 acc).
    canon = normaliza_lot_tp({"unit": "lot_pct", "rungs": [
        {"travel_pct": 5, "capital_pct": 1}, {"travel_pct": 10, "capital_pct": 50}]})
    res = _correr(*_lote_de_90(canon))
    assert _tamanos(res) == [1.0, 45.0]


def test_pct_de_siempre_sigue_en_fraccion():
    # Sin `unit`: 33 % de 90 = 29,7 (fracción), como siempre; el canónico sin `unit`.
    canon = normaliza_lot_tp({"rungs": [
        {"travel_pct": 5, "capital_pct": 33}, {"travel_pct": 10, "capital_pct": 33},
        {"travel_pct": 15, "capital_pct": 34}]})
    assert "unit" not in canon
    res = _correr(*_lote_de_90(canon))
    assert _tamanos(res) == [29.7, 29.7, 30.6]


def test_shares_acciones_fijas_con_tope_de_lo_que_queda():
    canon = normaliza_lot_tp({"unit": "shares", "rungs": [
        {"travel_pct": 5, "shares": 40}, {"travel_pct": 10, "shares": 40},
        {"travel_pct": 15, "shares": 40}]})
    assert canon == {"unit": "shares", "rungs": [(5.0, 40.0), (10.0, 40.0), (15.0, 40.0)]}
    res = _correr(*_lote_de_90(canon))
    assert _tamanos(res) == [40.0, 40.0, 10.0]


@pytest.mark.parametrize("lot_tp, msg", [
    ({"unit": "raro", "rungs": [{"travel_pct": 5, "capital_pct": 50}]}, "'unit'"),
    ({"unit": "shares", "rungs": [{"travel_pct": 5, "shares": 0}]}, "shares"),
    ({"unit": "shares", "rungs": [{"travel_pct": 5, "shares": 2.5}]}, "shares"),
    ({"unit": "shares", "rungs": [{"travel_pct": 5, "capital_pct": 50}]}, "shares"),
    ({"unit": "lot_pct", "rungs": [{"travel_pct": 5, "capital_pct": 60},
                                   {"travel_pct": 10, "capital_pct": 60}]}, "no puede pasar de 100"),
])
def test_validacion_de_unidades(lot_tp, msg):
    with pytest.raises(ValueError, match=msg):
        normaliza_lot_tp(lot_tp)


def test_compilador_lleva_la_unidad_al_nivel():
    d = {"bias": "short", "entry_logic": {"root_condition": {"logic": "AND", "conditions": []}},
         "exit_logic": {"root_condition": {"logic": "AND", "conditions": []}},
         "pyramiding": {"levels": [{
             "action": "add", "unit": "pct", "capital_pct": 10,
             "root_condition": {"logic": "AND", "conditions": [
                 {"indicator": "Close", "operator": ">", "value": 1}]},
             "lot_tp": {"unit": "shares", "rungs": [{"travel_pct": 5, "shares": 7}]}}]}}
    comp = compile_strategy_def(d)
    assert comp["pyramid_levels_def"][0]["lot_tp"] == {"unit": "shares", "rungs": [(5.0, 7.0)]}


@pytest.mark.parametrize("lot_tp", [
    {"rungs": [(5.0, 33.0), (10.0, 33.0), (15.0, 34.0)]},
    {"unit": "lot_pct", "rungs": [(5.0, 33.0), (10.0, 33.0), (15.0, 34.0)]},
    {"unit": "shares", "rungs": [(5.0, 40.0), (10.0, 40.0), (15.0, 40.0)]},
])
def test_paridad_dispatcher_jit_y_python(monkeypatch, lot_tp):
    """Con el kernel ACTIVO, una estrategia piramidada va al Python: el
    dispatcher y `portfolio_sim.simulate` dan exactamente lo mismo."""
    monkeypatch.setattr(sim_dispatch, "_numba_sim_enabled", lambda: True)
    args = _lote_de_90(lot_tp)
    directo = _correr(*args)
    import tests.test_tp_por_lote as base
    monkeypatch.setattr(base, "simulate", sim_dispatch.simulate)
    via_dispatch = base._correr(*args)
    assert via_dispatch["trades"] == directo["trades"]
