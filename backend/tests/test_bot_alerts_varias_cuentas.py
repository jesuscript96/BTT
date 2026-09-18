"""Varias cuentas por estrategia: una senal, un bloque por cuenta (18-sep-2026).

Jaume opera a veces la MISMA estrategia con dos cuentas de distinto riesgo
(300/300 y 200/200) y quiere UN mensaje de Telegram por senal con la cabecera
de siempre y, debajo, un bloque por cuenta separado por `------`, la de mas
riesgo primero. Lo que hay que garantizar:

  1. El motor expande cada estrategia en una entrada por cuenta (la principal
     con `cuenta None` y la clave de siempre) y corre el simulador por cuenta:
     las acciones de cada cuenta salen de SU riesgo, no de una regla de tres.
  2. Cada cuenta lleva su propio libro (acciones avisadas, tramos): el cuadre
     funciona por cuenta.
  3. Los eventos hermanos se agrupan en un mensaje; el id de cada evento lleva
     la cuenta (no se pisan en la base); la principal conserva el id de antes.
  4. Sin cuentas todo es exactamente como antes.
  5. La recarga en caliente distingue cuentas (anyadir una cuenta no recompila
     la principal ni pierde su memoria del dia).
"""
import numpy as np
import pandas as pd
import pytest

from app.services import bot_alerts_engine as mod
from app.services import bot_alerts_telegram as tg
from app.services.bot_alerts_cliente import id_evento

VENTANA = {"inicio": "04:00", "fin": "16:00"}


def _frame(n):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-09-18 04:00", periods=n, freq="1min"),
        "open": np.full(n, 2.0), "high": np.full(n, 2.0),
        "low": np.full(n, 2.0), "close": np.full(n, 2.0),
        "volume": np.full(n, 1000.0),
    })


def _def():
    return {"risk_management": {"size_by_sl": True}}


def _estrategia(cuentas=None):
    e = {"strategy_id": "pm1a", "name": "PM 1A", "definition": _def(),
         "riesgo_usd": 300.0, "riesgo_piramide_usd": 300.0, "ventana": VENTANA}
    if cuentas is not None:
        e["cuentas"] = cuentas
    return e


@pytest.fixture
def entorno(monkeypatch):
    """Traductor, compilador y simulador falsos. El simulador dimensiona por el
    riesgo que le llega (risk_r), como el de verdad: asi se ve que cada cuenta
    corre con SU riesgo."""
    guion = {"entrada_en": None, "cerrar": False, "riesgos_vistos": []}

    def falso_translate(frame, sdef, stats, compiled=None):
        n = len(frame)
        guion["n"] = n
        ent = np.zeros(n, dtype=bool)
        if guion["entrada_en"] is not None and guion["entrada_en"] < n:
            ent[guion["entrada_en"]] = True
        return {"direction": "Short", "entries": ent, "exits": np.zeros(n, dtype=bool),
                "accept_reentries": True, "max_reentries": -1, "sl_stop": None}

    def falso_kwargs(frame, senales, sdef, riesgo_usd, *a, **k):
        return {"risk_r": riesgo_usd}

    def falso_simulate(**kw):
        riesgo = kw["risk_r"]
        guion["riesgos_vistos"].append(riesgo)
        # Stop a 2,50 desde 2,00: 0,50 de distancia -> acciones = riesgo / 0,5
        size = riesgo / 0.5 * 1.01          # el relleno del simulador, algo distinto
        if guion.get("n", 0) <= 3:
            return {"trades": []}            # en la vela de senal aun no hay trade
        if guion["cerrar"]:
            return {"trades": [{"entry_idx": 3, "exit_idx": 6, "size": size,
                                "exit_price": 2.5, "exit_reason": "SL", "status": "Closed"}]}
        if guion["entrada_en"] is not None:
            return {"trades": [{"entry_idx": 3, "exit_idx": 9, "size": size,
                                "exit_price": 2.0, "exit_reason": "EOD", "status": "Open"}]}
        return {"trades": []}

    monkeypatch.setattr(mod, "translate_strategy", falso_translate)
    monkeypatch.setattr(mod, "_kwargs_simulate", falso_kwargs)
    monkeypatch.setattr(mod, "simulate", falso_simulate)
    monkeypatch.setattr(mod, "compile_strategy_def", lambda sdef: {"compilada": True})
    monkeypatch.setattr(mod, "stop_estimado", lambda *a, **k: 2.5)
    monkeypatch.setattr(mod, "calcular_acciones",
                        lambda riesgo, precio, stop, *a, **k: riesgo / abs(precio - stop))
    return guion


def _senal(motor, guion, n=3, entrada_en=2):
    guion["entrada_en"] = entrada_en
    guion["cerrar"] = False
    return motor.procesar_vela("KXIN", _frame(n), {})


def test_sin_cuentas_todo_igual_que_antes(entorno):
    m = mod.MotorAlertas([_estrategia()])
    assert len(m.estrategias) == 1
    assert m.estrategias[0]["cuenta"] is None
    assert m.estrategias[0]["clave"] == "pm1a"
    evs = _senal(m, entorno)
    assert [e.tipo for e in evs] == ["entrada"]
    assert evs[0].cuenta is None and evs[0].acciones == 600      # 300 / 0,5
    assert id_evento(evs[0]) == "KXIN|pm1a|2026-09-18 04:02:00|entrada"


def test_dos_cuentas_dos_eventos_cada_uno_con_su_riesgo(entorno):
    m = mod.MotorAlertas([_estrategia([{"nombre": "IBKR", "riesgo_usd": 200}])])
    assert [e["cuenta"] for e in m.estrategias] == [None, "IBKR"]
    assert m.estrategias[1]["clave"] == "pm1a::IBKR"
    assert m.estrategias[1]["compiled"] is m.estrategias[0]["compiled"], "la compilacion se comparte"
    evs = _senal(m, entorno)
    assert [(e.cuenta, e.acciones, e.riesgo_usd) for e in evs] == [(None, 600, 300.0), ("IBKR", 400, 200.0)]
    assert sorted(entorno["riesgos_vistos"]) == [200.0, 300.0], "el simulador corre una vez por cuenta con SU riesgo"
    assert id_evento(evs[0]) == "KXIN|pm1a|2026-09-18 04:02:00|entrada"
    assert id_evento(evs[1]) == "KXIN|pm1a|2026-09-18 04:02:00|entrada|IBKR"


def test_el_cierre_cuadra_por_cuenta(entorno):
    m = mod.MotorAlertas([_estrategia([{"nombre": "IBKR", "riesgo_usd": 200}])])
    _senal(m, entorno)
    entorno["cerrar"] = True
    evs = m.procesar_vela("KXIN", _frame(7), {})
    salidas = [e for e in evs if e.tipo == "salida"]
    assert [(e.cuenta, e.acciones) for e in salidas] == [(None, 600.0), ("IBKR", 400.0)], \
        "cada cuenta cierra lo que ELLA aviso (no lo del simulador, que era 606 / 404)"


def test_un_mensaje_con_un_bloque_por_cuenta_mayor_riesgo_primero(entorno):
    m = mod.MotorAlertas([_estrategia([{"nombre": "IBKR", "riesgo_usd": 200},
                                       {"nombre": "GRANDE", "riesgo_usd": 500}])])
    evs = _senal(m, entorno)
    grupos = tg.agrupar(evs)
    assert len(grupos) == 1, "misma senal, tres cuentas: UN mensaje"
    assert [e.cuenta for e in grupos[0]] == ["GRANDE", None, "IBKR"], "de mas a menos riesgo"
    texto = tg.formatear_grupo(grupos[0])
    assert texto.count(tg.SEPARADOR) == 2
    assert texto.index("[GRANDE]") < texto.index("[principal]") < texto.index("[IBKR]")
    assert "Acciones: <b>1.000</b>" in texto and "Acciones: <b>600</b>" in texto and "Acciones: <b>400</b>" in texto
    assert texto.count("Precio:") == 1 and texto.count("KXIN") == 1, "cabecera y precio una sola vez"
    assert len(texto.splitlines()) <= 8, "al grano"


def test_una_cuenta_sin_etiquetas_ni_separador(entorno):
    m = mod.MotorAlertas([_estrategia()])
    evs = _senal(m, entorno)
    texto = tg.formatear(evs[0])
    assert tg.SEPARADOR not in texto and "[principal]" not in texto
    assert "Acciones: <b>600</b>" in texto and "Stop: 2,5000" in texto and "Riesgo: 300" in texto


def test_agrupar_no_mezcla_senales_distintas(entorno):
    m = mod.MotorAlertas([_estrategia([{"nombre": "IBKR", "riesgo_usd": 200}])])
    evs = _senal(m, entorno)
    otro = mod.Evento(tipo="entrada", ticker="OTRO", strategy_id="pm1a", estrategia="PM 1A",
                      momento=evs[0].momento, precio=1.0, direccion="Short", acciones=10, riesgo_usd=300)
    grupos = tg.agrupar(evs + [otro])
    assert [len(g) for g in grupos] == [2, 1]


def test_actualizar_anyade_cuenta_sin_recompilar_la_principal(entorno):
    m = mod.MotorAlertas([_estrategia()])
    principal = m.estrategias[0]
    _senal(m, entorno)                              # la principal ya aviso
    res = m.actualizar([_estrategia([{"nombre": "IBKR", "riesgo_usd": 200}])])
    assert res["anyadidas"] == ["PM 1A [IBKR]"] and res["cambiadas"] == []
    assert m.estrategias[0] is principal, "la principal no se recompila"
    # Misma vela otra vez: la principal NO repite su aviso (memoria intacta);
    # la cuenta nueva avisa por primera vez.
    evs = m.procesar_vela("KXIN", _frame(3), {})
    assert [(e.cuenta, e.tipo) for e in evs] == [("IBKR", "entrada")]
    res2 = m.actualizar([_estrategia()])
    assert res2["quitadas"] == ["PM 1A [IBKR]"]
