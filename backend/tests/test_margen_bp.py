# -*- coding: utf-8 -*-
"""Criterios de margen y buying power (19-sep-2026): la tabla de SageTrader y
el recorrido cronologico del dia que corta lo que no cabe."""
import numpy as np
import pytest

from app.services.margen import (
    ConfigMargen,
    RegistroMargen,
    aplicar_margen_dia,
    eventos_ticker_dia,
    primera_violacion,
    requisito_por_accion,
)


def test_tabla_sagetrader_cortos_por_precio():
    # < 2,50 $: 2,50 $ por accion (a 0,50 $ es el 500 % del nocional)
    assert requisito_por_accion(0.50, True) == 2.50
    assert requisito_por_accion(2.49, True) == 2.50
    # 2,50-5 $: el 100 % del valor
    assert requisito_por_accion(2.50, True) == 2.50
    assert requisito_por_accion(3.0, True) == 3.0
    assert requisito_por_accion(4.99, True) == 4.99
    # >= 5 $: el mayor de 30 % o 5 $
    assert requisito_por_accion(5.0, True) == 5.0
    assert requisito_por_accion(10.0, True) == 5.0
    assert requisito_por_accion(20.0, True) == pytest.approx(6.0)
    # largos: 25 % (4:1)
    assert requisito_por_accion(3.0, False) == pytest.approx(0.75)
    assert requisito_por_accion(0, True) == 0.0


def test_config_valida_broker_y_capacidad():
    c = ConfigMargen(broker="loquesea", capacidad_pct=100)
    assert c.broker == "sagetrader"
    with pytest.raises(ValueError):
        ConfigMargen(capacidad_pct=0)


def _ticker_dia(ticker, legs, n_bars=60, t0=4 * 3600):
    """Un ticker-dia sintetico: timestamps de 1 min (ns) y los legs crudos."""
    ts = np.array([(t0 + 60 * i) * 1_000_000_000 for i in range(n_bars)], dtype=np.int64)
    return {"ticker": ticker, "date": "2026-01-02", "sim_kwargs": {"timestamps": ts},
            "sim_result": {"trades": legs}}


def _leg(entry_idx, exit_idx, size, price, direction="Short", adds=None):
    return {"entry_idx": entry_idx, "exit_idx": exit_idx, "size": size, "entry_price": price,
            "direction": direction, "pyr_executions": adds or []}


def test_eventos_de_un_ticker_dia():
    # Corto de 1.000 acciones a 1 $ en la vela 10, cierre en la 30: exige 2.500 $.
    e = _ticker_dia("AAA", [_leg(10, 30, 1000, 1.0)])
    ev = eventos_ticker_dia(e["sim_result"]["trades"], e["sim_kwargs"]["timestamps"], "sagetrader")
    tomas = [x for x in ev if x[3]]
    libera = [x for x in ev if not x[3]]
    assert len(tomas) == 1 and tomas[0][2] == pytest.approx(2500.0)
    assert len(libera) == 1 and libera[0][2] == pytest.approx(-2500.0)
    assert tomas[0][0] == 4 * 3600 + 600 and libera[0][0] == 4 * 3600 + 1800
    # La decision de esa entrada es la vela anterior (fill en i+1).
    assert tomas[0][6] == 4 * 3600 + 540


def test_primera_violacion_es_cronologica_entre_tickers():
    # Equity 10.000: AAA (04:10, 1.000 acc a 1 $ -> 2.500 $) cabe; BBB (04:15,
    # 3.000 acc a 1 $ -> 7.500 $) cabe justo; CCC (04:20, 100 acc a 1 $ ->
    # 250 $) YA NO cabe (10.000 usados) hasta que AAA sale a las 04:30.
    pend = [
        _ticker_dia("AAA", [_leg(10, 30, 1000, 1.0)]),
        _ticker_dia("BBB", [_leg(15, 40, 3000, 1.0)]),
        _ticker_dia("CCC", [_leg(20, 25, 100, 1.0)]),
    ]
    v = primera_violacion(pend, 10000.0, "sagetrader")
    assert v["i"] == 2 and v["t"] == 4 * 3600 + 1200
    assert v["usado"] == pytest.approx(10000.0) and v["requisito"] == pytest.approx(250.0)
    # Con capacidad de sobra, nada.
    assert primera_violacion(pend, 50000.0, "sagetrader")["i"] is None


def test_aplicar_margen_dia_corta_al_que_no_cabe_y_no_a_los_demas():
    pend = [
        _ticker_dia("AAA", [_leg(10, 30, 1000, 1.0)]),
        _ticker_dia("BBB", [_leg(15, 40, 3000, 1.0)]),
        _ticker_dia("CCC", [_leg(20, 25, 100, 1.0)]),
    ]
    resims = []

    def simulate_fn(**kw):
        # El motor sin riesgo nuevo desde T: aqui, el ticker se queda sin trades
        # (su unica entrada era en T).
        resims.append(kw["no_new_risk_after"])
        return {"trades": []}

    cfg = ConfigMargen()
    reg = RegistroMargen(cfg=cfg)
    dia = aplicar_margen_dia(pend, 10000.0, cfg, simulate_fn, "2026-01-02")
    reg.dias.append(dia)
    assert len(dia["bloqueos"]) == 1 and dia["bloqueos"][0]["ticker"] == "CCC"
    # El corte va en la vela de la DECISION (la anterior al fill de la 04:20).
    assert resims == [(4 * 3600 + 1140) * 1_000_000_000]
    assert pend[2]["sim_result"]["trades"] == [] and pend[0]["sim_result"]["trades"] and pend[1]["sim_result"]["trades"]
    assert pend[2]["sim_kwargs"]["no_new_risk_after"] == (4 * 3600 + 1140) * 1_000_000_000
    assert dia["pico"] == pytest.approx(10000.0)
    r = reg.resumen()
    assert r["bloqueos"] == 1 and r["dias_con_bloqueo"] == 1 and r["broker"] == "sagetrader"


def test_los_anadidos_tambien_consumen_y_las_salidas_liberan():
    # AAA: 1.000 acc a 1 $ (2.500 $) + anadido de 2.000 acc a 1 $ a las 04:12
    # (5.000 $) -> 7.500 $ abiertos. BBB a las 04:14 pide 3.000 $: no cabe con
    # 10.000. Tras la salida de AAA (04:30) si cabria, pero llega antes.
    aaa = _leg(10, 30, 3000, 1.0, adds=[{"kind": "add", "time_epoch": 4 * 3600 + 720, "size": 2000, "price": 1.0}])
    pend = [_ticker_dia("AAA", [aaa]), _ticker_dia("BBB", [_leg(14, 40, 1200, 1.0)])]
    v = primera_violacion(pend, 10000.0, "sagetrader")
    assert v["i"] == 1 and v["usado"] == pytest.approx(7500.0) and v["requisito"] == pytest.approx(3000.0)
    # Con BBB una vela despues de la salida de AAA, cabe.
    pend[1] = _ticker_dia("BBB", [_leg(31, 40, 1200, 1.0)])
    assert primera_violacion(pend, 10000.0, "sagetrader")["i"] is None


# ── Con el simulador de verdad ──────────────────────────────────────────

def _serie(precios, entradas_en, salidas_en=(), t0_min=0):
    n = len(precios)
    close = np.asarray(precios, dtype=np.float64)
    entries = np.zeros(n, dtype=bool)
    for i in entradas_en:
        entries[i] = True
    exits = np.zeros(n, dtype=bool)
    for i in salidas_en:
        exits[i] = True
    ts = ((np.arange(n) + t0_min) * 60_000_000_000).astype(np.int64)
    return dict(close=close, open_=close, high=close * 1.001, low=close * 0.999,
                entries=entries, exits=exits, timestamps=ts)


def _pend_real(ticker, precios, entradas_en, salidas_en, risk_r, direction="shortonly"):
    from app.services.portfolio_sim import simulate
    kw = dict(_serie(precios, entradas_en, salidas_en), direction=direction, init_cash=10_000.0,
              risk_r=risk_r, risk_type="FIXED", accumulate=True, max_reentries=-1)
    return {"ticker": ticker, "date": "2026-01-05", "sim_kwargs": kw, "sim_result": simulate(**kw)}


def test_con_el_simulador_real_corta_solo_la_entrada_que_no_cabe():
    """Tres cortos a 1 $ (2,50 $/acc de margen). AAA (min 1) 2.000 acc = 5.000;
    BBB (min 3) 1.600 acc = 4.000 -> 9.000 usados; CCC (min 5) 1.000 acc = 2.500:
    NO cabe en 10.000. AAA sale en la vela 8, luego CCC cabria si entrara despues.
    """
    from app.services.portfolio_sim import simulate
    px = [1.0] * 12
    pend = [
        _pend_real("AAA", px, [1], [8], risk_r=2000.0),
        _pend_real("BBB", px, [3], [10], risk_r=1600.0),
        _pend_real("CCC", px, [5], [9], risk_r=1000.0),
    ]
    assert all(len(e["sim_result"]["trades"]) == 1 for e in pend), "el caso base opera los tres"
    # La entrada se ejecuta en la vela siguiente a la senal (i+1).
    assert pend[2]["sim_result"]["trades"][0]["entry_idx"] == 6
    cfg = ConfigMargen()
    dia = aplicar_margen_dia(pend, 10_000.0, cfg, simulate, "2026-01-05")
    assert [b["ticker"] for b in dia["bloqueos"]] == ["CCC"]
    assert pend[2]["sim_result"]["trades"] == [], "CCC no entra: no cabe en el margen"
    assert len(pend[0]["sim_result"]["trades"]) == 1 and len(pend[1]["sim_result"]["trades"]) == 1
    assert dia["pico"] == pytest.approx(9000.0) and dia["pico_pct"] == pytest.approx(90.0)
    # Con el doble de equity cabe todo y no se toca nada.
    pend2 = [_pend_real("AAA", px, [1], [8], 2000.0), _pend_real("BBB", px, [3], [10], 1600.0),
             _pend_real("CCC", px, [5], [9], 1000.0)]
    dia2 = aplicar_margen_dia(pend2, 20_000.0, cfg, simulate, "2026-01-05")
    assert dia2["bloqueos"] == [] and all(len(e["sim_result"]["trades"]) == 1 for e in pend2)


def test_con_el_simulador_real_una_reentrada_posterior_si_cabe():
    """CCC tiene dos senales: la vela 5 (no cabe) y la vela 9 (AAA ya salio en la
    8: cabe). El corte es «sin riesgo nuevo desde T»: el ticker pierde TODO el
    resto del dia, tambien la segunda senal (misma semantica que el
    cortacircuitos; lo abierto sigue hasta su salida)."""
    from app.services.portfolio_sim import simulate
    px = [1.0] * 14
    pend = [
        _pend_real("AAA", px, [1], [8], risk_r=2000.0),
        _pend_real("BBB", px, [3], [12], risk_r=1600.0),
        _pend_real("CCC", px, [5, 9], [7, 11], risk_r=1000.0),
    ]
    assert len(pend[2]["sim_result"]["trades"]) == 2
    dia = aplicar_margen_dia(pend, 10_000.0, ConfigMargen(), simulate, "2026-01-05")
    assert [b["ticker"] for b in dia["bloqueos"]] == ["CCC"]
    assert pend[2]["sim_result"]["trades"] == []
