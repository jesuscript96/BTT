"""SL y TP POR LOTE en el bot de alertas.

LO QUE PASABA (24-sep-2026). El simulador apunta el cierre de un lote en
`pyr_executions` como `lot_stop` / `lot_tp` y ademas emite su leg de cierre. El
bot solo conocia 'add' y 'reduce': el cierre del lote llegaba como
«➕ AÑADIR 100 (posicion total 484)», luego como «CIERRE PARCIAL 124» y el
cierre final decia 360 cuando se tenian 284.

LO QUE HAY QUE GARANTIZAR:
  1. El cierre de un lote se avisa UNA vez, como STOP/TP DE LOTE, restando.
  2. El cierre posterior cuadra con lo que queda.
  3. Anyadir y reducir no cambian en nada.
Se prueba vela a vela con el simulador REAL (el bot resimula el frame entero
en cada vela) y con el guion de `test_bot_alerts_cantidades_cuadradas`.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import bot_alerts_engine as mod
from app.services.bot_alerts_telegram import formatear
from app.services.portfolio_sim import simulate as simulate_real

N = 16
VENTANA = {"inicio": "04:00", "fin": "20:00"}
EST = {"strategy_id": "s", "name": "S", "definition": {"risk_management": {}},
       "compiled": None, "riesgo_usd": 100.0, "ventana": VENTANA}


def _dia(highs=None, lows=None):
    o = np.full(N, 10.0)
    c = np.full(N, 10.0)
    h = np.full(N, 10.05)
    lo = np.full(N, 9.95)
    for k, v in (highs or {}).items():
        h[k] = v
    for k, v in (lows or {}).items():
        lo[k] = v
    ts = pd.date_range("2026-09-22 04:00", periods=N, freq="1min")
    return o, h, lo, c, ts


def _senal(*barras):
    s = np.zeros(N, dtype=bool)
    for b in barras:
        s[b] = True
    return s


def _reduce(barra, frac):
    return {"signals": _senal(barra), "action": "reduce", "capital_frac": frac,
            "max_fires": 1, "unit": "pct", "amount_usd": 0.0, "size_by_sl": False,
            "hybrid_stop": False, "hybrid_black_swan_pct": None, "hybrid_max_loss_pct": None}


def _nivel(lot_stop=None, lot_tp=None, max_fires=1):
    nv = {"signals": _senal(4), "action": "add", "capital_frac": 0.0,
          "max_fires": max_fires, "unit": "usd", "amount_usd": 100.0,
          "size_by_sl": False, "hybrid_stop": False,
          "hybrid_black_swan_pct": None, "hybrid_max_loss_pct": None}
    if lot_stop:
        nv["lot_stop"] = lot_stop
    if lot_tp:
        nv["lot_tp"] = lot_tp
    return nv


def _correr_bot(monkeypatch, dia, niveles, avisadas=10.0):
    """Corto a 10 $ (senal en la vela 1, 10 acciones en el simulador), un
    anyadido de 10 acciones (senal en la 4, fill en la 5) y salida por senal en
    la 12. El bot procesa vela a vela; devuelve todos los avisos."""
    o, h, lo, c, ts = dia
    entries, exits = _senal(1), _senal(12)
    ts_ns = ts.values.astype("datetime64[ns]").astype(np.int64)
    hods, lods = np.maximum.accumulate(h), np.minimum.accumulate(lo)

    def kwargs(frame, senales, *a, **k):
        n = len(frame)
        return dict(close=c[:n], open_=o[:n], high=h[:n], low=lo[:n],
                    entries=entries[:n], exits=exits[:n], direction="shortonly",
                    init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
                    fees=0.0, fee_type="PERCENT", slippage=0.0,
                    look_ahead_prevention=True, pyramid_levels=niveles,
                    pyramid_sequential=False, timestamps=ts_ns[:n],
                    hods=hods[:n], lods=lods[:n], prev_highs=hods[:n], prev_lows=lods[:n])

    def translate(frame, sdef, stats, compiled=None):
        n = len(frame)
        return {"direction": "Short", "entries": entries[:n], "exits": exits[:n],
                "accept_reentries": False, "max_reentries": -1}

    monkeypatch.setattr(mod, "translate_strategy", translate)
    monkeypatch.setattr(mod, "_kwargs_simulate", kwargs)
    monkeypatch.setattr(mod, "simulate", simulate_real)
    monkeypatch.setattr(mod, "stop_estimado", lambda *a, **k: 10.5)
    monkeypatch.setattr(mod, "calcular_acciones", lambda *a, **k: avisadas)

    m = mod.MotorAlertas([])
    frame = pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": lo,
                          "close": c, "volume": np.full(N, 1000.0)})
    avisos = []
    for n in range(2, N + 1):
        avisos += m._procesar_estrategia("T", frame.iloc[:n].reset_index(drop=True), {}, EST)
    _correr_bot.motor = m
    return avisos


def _resumen(avisos):
    return [(a.tipo, a.accion_piramide, a.acciones, a.posicion_total) for a in avisos]


def test_sl_de_lote_se_avisa_una_vez_y_el_cierre_cuadra(monkeypatch):
    # SL del lote al 5 %: 10,50; la vela 7 llega a 10,60.
    av = _correr_bot(monkeypatch, _dia(highs={7: 10.6}),
                     [_nivel(lot_stop={"mode": "pct", "pct": 5.0})])
    assert _resumen(av) == [
        ("entrada", None, 10.0, None),
        ("piramide", "add", 10.0, 20.0),
        ("piramide", "lot_stop", 10.0, 10.0),
        ("salida", None, 10.0, 10.0),
    ]
    assert "STOP DE LOTE" in formatear(av[2]) and "➖" in formatear(av[2])
    assert av[3].posicion_restante == 0.0


def test_sl_de_lote_en_la_vela_del_fill_no_se_pierde(monkeypatch):
    """El cinturon puede saltar en la misma vela en que entra el anyadido:
    mismo nivel y misma vela que el 'add'. Antes la clave (nivel, vela) se
    comia uno de los dos."""
    av = _correr_bot(monkeypatch, _dia(highs={5: 10.6}),
                     [_nivel(lot_stop={"mode": "pct", "pct": 5.0})])
    tipos = [(a.tipo, a.accion_piramide) for a in av]
    assert ("piramide", "add") in tipos and ("piramide", "lot_stop") in tipos
    assert av[-1].tipo == "salida" and av[-1].acciones == 10.0


def test_dos_rungs_del_tp_en_la_misma_vela(monkeypatch):
    # Rungs 50 % a +5 % (9,50) y 50 % a +10 % (9,00); la vela 7 llega a 8,90.
    av = _correr_bot(monkeypatch, _dia(lows={7: 8.9}),
                     [_nivel(lot_tp={"rungs": [(5.0, 50.0), (10.0, 50.0)]})])
    assert _resumen(av) == [
        ("entrada", None, 10.0, None),
        ("piramide", "add", 10.0, 20.0),
        ("piramide", "lot_tp", 5.0, 15.0),
        ("piramide", "lot_tp", 5.0, 10.0),
        ("salida", None, 10.0, 10.0),
    ]
    assert "TP DE LOTE" in formatear(av[2])


def test_con_lo_avisado_distinto_del_simulador(monkeypatch):
    """Se avisaron 9 (el simulador lleva 10): el lote cierra sus 10 y la salida
    cierra las 9 que quedan de verdad."""
    av = _correr_bot(monkeypatch, _dia(highs={7: 10.6}),
                     [_nivel(lot_stop={"mode": "pct", "pct": 5.0})], avisadas=9.0)
    assert _resumen(av)[1:] == [
        ("piramide", "add", 10.0, 19.0),
        ("piramide", "lot_stop", 10.0, 9.0),
        ("salida", None, 9.0, 9.0),
    ]


# ── REDUCIR (24-sep): se avisaba DOS veces y el cierre final descuadraba ──
# Antes: «➖ REDUCIR 5» + «CIERRE PARCIAL · Pyramid Reduce» + un cierre final
# que no cuadraba con lo que quedaba.

def test_reducir_se_avisa_una_vez_y_el_cierre_cuadra(monkeypatch):
    av = _correr_bot(monkeypatch, _dia(), [_reduce(4, 0.5)])
    assert _resumen(av) == [
        ("entrada", None, 10.0, None),
        ("piramide", "reduce", 5.0, 5.0),
        ("salida", None, 5.0, 5.0),
    ]
    assert "REDUCIR" in formatear(av[1])
    assert av[2].posicion_restante == 0.0


def test_anyadir_y_luego_reducir(monkeypatch):
    av = _correr_bot(monkeypatch, _dia(), [_nivel(), _reduce(7, 0.5)])
    assert _resumen(av) == [
        ("entrada", None, 10.0, None),
        ("piramide", "add", 10.0, 20.0),
        ("piramide", "reduce", 10.0, 10.0),
        ("salida", None, 10.0, 10.0),
    ]


def test_reducir_con_lo_avisado_distinto_del_simulador(monkeypatch):
    """Se avisaron 9 (el simulador lleva 10): la reduccion es la MISMA fraccion
    sobre lo avisado y todo lo que se cierra suma exactamente lo abierto."""
    av = _correr_bot(monkeypatch, _dia(), [_nivel(), _reduce(7, 0.5)], avisadas=9.0)
    _ent, add, red, sal = av
    assert (add.acciones, add.posicion_total) == (10.0, 19.0)
    assert red.acciones + red.posicion_total == 19.0
    assert sal.acciones == red.posicion_total and sal.posicion_restante == 0.0


def test_reducir_el_100_cierra_todo_y_rearma(monkeypatch):
    """La reduccion vacia la posicion: no hay trade de cierre, asi que no hay
    aviso de salida; la piramide cierra todo lo avisado y la senal se rearma."""
    av = _correr_bot(monkeypatch, _dia(), [_reduce(4, 1.0)], avisadas=9.0)
    assert _resumen(av) == [
        ("entrada", None, 9.0, None),
        ("piramide", "reduce", 9.0, 0.0),
    ]
    estado = next(iter(_correr_bot.motor._estado.values()))
    assert estado.idx_ultimo_cierre_avisado > estado.idx_ultima_entrada_avisada


def test_la_prealerta_no_avisa_cierres_de_lote(monkeypatch):
    """Como las salidas: un stop puede tocarse y recuperarse dentro del minuto."""
    ev = mod.Evento(tipo="piramide", ticker="T", strategy_id="s", estrategia="S",
                    momento=pd.Timestamp("2026-09-22 04:07"), precio=10.5,
                    direccion="Short", acciones=10.0, accion_piramide="lot_stop")
    m = mod.MotorAlertas([])
    monkeypatch.setattr(m, "procesar_vela", lambda *a, **k: [ev])
    assert m.mirar_sin_marcar("T", pd.DataFrame()) == []
