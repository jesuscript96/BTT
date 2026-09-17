"""Las cantidades de los avisos tienen que CUADRAR: se sale con lo que se entro.

LO QUE PASABA (16-sep-2026). El aviso de entrada dimensiona con el cierre de
la vela de senal (es lo unico que hay cuando se avisa). El simulador rellena
en la apertura de la vela siguiente y calcula SUS acciones con ese precio. Las
salidas y las piramides salian de los trades del simulador, asi que:

    MEDS  (RTH 1B)  entrada avisada 284  ->  stop avisado «cierra 289»
    RETO  (RTH 1B)  entrada avisada 208  ->  stop avisado «cierra 210»
    SUGP  (15-sep)  entrada avisada 1.056 -> stop avisado «cierra 1.095»
    MEDS  (PM 1A)   507 + piramide 359 = 866 -> «posicion queda en 890»

Jaume: «debe salir con las mismas que entra, y si ha anyadido pues con las que
toque, al igual que con los parciales. Las cantidades deben estar cuadradas».

LO QUE HAY QUE GARANTIZAR:
  1. La entrada se avisa en acciones ENTERAS y se recuerda.
  2. Un cierre total cierra exactamente lo avisado, no lo del simulador.
  3. Los tramos parciales son la misma fraccion que en el simulador pero sobre
     lo avisado, enteros, y SUMAN exactamente lo avisado (el ultimo se lleva
     el resto).
  4. Una piramide dice «posicion queda en» entrada avisada + anyadido, y el
     cierre posterior cuadra con ese total.
  5. Una posicion heredada (entrada NO avisada, p. ej. al hidratar el dia) se
     sigue avisando con las cantidades del simulador: no hay verdad avisada.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import bot_alerts_engine as mod

VENTANA = {"inicio": "04:00", "fin": "16:00"}


def _frame(n):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-09-16 09:30", periods=n, freq="1min"),
        "open": np.full(n, 4.31), "high": np.full(n, 4.31),
        "low": np.full(n, 4.31), "close": np.full(n, 4.31),
        "volume": np.full(n, 1000.0),
    })


@pytest.fixture
def motor(monkeypatch):
    """Simulador y traductor sustituidos. La prueba decide en que vela hay senal
    de entrada y que trades devuelve el simulador en cada vela."""
    guion = {"trades": [], "entrada_en": None}

    def falso_translate(frame, sdef, stats, compiled=None):
        n = len(frame)
        ent = np.zeros(n, dtype=bool)
        if guion["entrada_en"] is not None and guion["entrada_en"] < n:
            ent[guion["entrada_en"]] = True
        return {"direction": "Short", "entries": ent, "exits": np.zeros(n, dtype=bool),
                "accept_reentries": True, "max_reentries": -1}

    monkeypatch.setattr(mod, "translate_strategy", falso_translate)
    monkeypatch.setattr(mod, "simulate", lambda **kw: {"trades": list(guion["trades"])})
    monkeypatch.setattr(mod, "_kwargs_simulate", lambda *a, **k: {})
    monkeypatch.setattr(mod, "stop_estimado", lambda *a, **k: 4.8379)
    # El aviso real de MEDS: 150 / (4,8379 − 4,31) = 284,1 acciones.
    monkeypatch.setattr(mod, "calcular_acciones", lambda *a, **k: 284.1)

    m = mod.MotorAlertas([])
    m._guion = guion
    return m


EST = {
    "strategy_id": "rth1b", "name": "Estrategia RTH. 1B TTP (50k)",
    "definition": {"risk_management": {"size_by_sl": True}},
    "compiled": None, "riesgo_usd": 150.0, "ventana": VENTANA,
}

# El simulador rellena en la vela siguiente (entry_idx = senal + 1) a 4,3189 y
# le salen 289,1 acciones: el desvio real del 16-sep.
SIM = 289.1


def _abierto(size=SIM, entry_idx=3, exit_idx=9, pyr=None):
    """La posicion viva: el trade sintetico EOD en el borde del frame."""
    t = {"entry_idx": entry_idx, "exit_idx": exit_idx, "size": size,
         "exit_price": 4.31, "exit_reason": "EOD", "status": "Open"}
    if pyr:
        t["pyr_executions"] = pyr
    return t


def _cerrado(size, motivo, exit_idx, entry_idx=3, precio=4.8379, pyr=None):
    t = {"entry_idx": entry_idx, "exit_idx": exit_idx, "size": size,
         "exit_price": precio, "exit_reason": motivo, "status": "Closed"}
    if pyr:
        t["pyr_executions"] = pyr
    return t


def _vela(motor, n, trades, entrada_en=None):
    motor._guion["trades"] = trades
    motor._guion["entrada_en"] = entrada_en
    return motor._procesar_estrategia("MEDS", _frame(n), {}, EST)


def _entrar(motor):
    """Vela 3: senal de entrada, se avisa. Devuelve el aviso."""
    ev = _vela(motor, 3, [], entrada_en=2)
    assert [e.tipo for e in ev] == ["entrada"]
    return ev[0]


# ── 1 y 2. entera, recordada, y el cierre total la respeta ────────────────
def test_la_entrada_es_entera_y_el_stop_cierra_lo_avisado(motor):
    ent = _entrar(motor)
    assert ent.acciones == 284.0, "284,1 se avisa como 284 acciones enteras"

    # vela 4: el simulador ya ha rellenado (entry_idx 3) con 289,1
    ev = _vela(motor, 5, [_abierto(exit_idx=4)])
    assert ev == []

    # vela 5: salta el stop; el simulador cierra 289,1
    ev = _vela(motor, 6, [_cerrado(SIM, "SL", exit_idx=5)])
    assert [e.tipo for e in ev] == ["salida"]
    s = ev[0]
    assert s.acciones == 284.0, f"cerro {s.acciones}, y se entro con 284"
    assert s.posicion_total == 284.0
    assert s.posicion_restante == 0.0


# ── 3. los tramos parciales suman exactamente lo avisado ──────────────────
def test_los_tramos_parciales_suman_lo_avisado(motor):
    _entrar(motor)
    # 25 % / 50 % / 25 % del simulador sobre 289,1
    t1, t2, t3 = SIM * 0.25, SIM * 0.50, SIM * 0.25

    ev = _vela(motor, 8, [_cerrado(t1, "Partial TP (Hour)", 7), _abierto(t2 + t3, exit_idx=7)])
    assert len(ev) == 1 and ev[0].acciones == 71.0            # round(284 · 0,25)
    assert ev[0].posicion_total == 284.0 and ev[0].posicion_restante == 213.0

    ev = _vela(motor, 9, [_cerrado(t1, "Partial TP (Hour)", 7), _cerrado(t2, "Partial TP (Hour)", 8),
                          _abierto(t3, exit_idx=8)])
    assert len(ev) == 1 and ev[0].acciones == 142.0           # round(284 · 0,50)
    assert ev[0].posicion_restante == 71.0

    ev = _vela(motor, 10, [_cerrado(t1, "Partial TP (Hour)", 7), _cerrado(t2, "Partial TP (Hour)", 8),
                           _cerrado(t3, "Partial TP (Hour)", 9)])
    assert len(ev) == 1 and ev[0].acciones == 71.0            # el resto: 284 − 71 − 142
    assert ev[0].posicion_restante == 0.0


def test_con_redondeos_incomodos_el_ultimo_tramo_cierra_la_suma(motor, monkeypatch):
    """Tres tramos iguales de 100 avisadas: 33 + 33 + 34, nunca 33 + 33 + 33."""
    monkeypatch.setattr(mod, "calcular_acciones", lambda *a, **k: 100.4)
    _entrar(motor)
    sim = 103.0
    t = sim / 3
    ev1 = _vela(motor, 8, [_cerrado(t, "Partial TP (Hour)", 7), _abierto(2 * t, exit_idx=7)])
    ev2 = _vela(motor, 9, [_cerrado(t, "Partial TP (Hour)", 7), _cerrado(t, "Partial TP (Hour)", 8),
                           _abierto(t, exit_idx=8)])
    ev3 = _vela(motor, 10, [_cerrado(t, "Partial TP (Hour)", 7), _cerrado(t, "Partial TP (Hour)", 8),
                            _cerrado(t, "Partial TP (Hour)", 9)])
    cierres = [ev1[0].acciones, ev2[0].acciones, ev3[0].acciones]
    assert cierres == [33.0, 33.0, 34.0]
    assert sum(cierres) == 100.0


# ── 4. la piramide cuadra con lo avisado ──────────────────────────────────
def test_la_piramide_suma_sobre_lo_avisado_y_el_cierre_lo_respeta(motor):
    _entrar(motor)
    # el simulador anyade 73,2 en la vela 6 y su posicion pasa a 362,3
    pyr = [{"kind": "add", "level": 0, "idx": 6, "price": 4.20, "size": 73.2,
            "position_size": SIM + 73.2}]
    ev = _vela(motor, 8, [_abierto(SIM + 73.2, exit_idx=7, pyr=pyr)])
    assert [e.tipo for e in ev] == ["piramide"]
    p = ev[0]
    assert p.acciones == 73.0
    assert p.posicion_total == 357.0, "284 avisadas + 73 anyadidas, no 362 del simulador"

    # cierre total por stop: el simulador cierra 362,3; a Jaume se le dice 357
    ev = _vela(motor, 9, [_cerrado(SIM + 73.2, "SL", 8, pyr=pyr)])
    assert len(ev) == 1
    assert ev[0].acciones == 357.0 and ev[0].posicion_total == 357.0
    assert ev[0].posicion_restante == 0.0


# ── 5. sin entrada avisada, se dan las cantidades del simulador ───────────
def test_una_posicion_heredada_sigue_con_las_cantidades_del_simulador(motor):
    """El bot arranca con la posicion ya abierta (hidratacion): nunca aviso la
    entrada, asi que no hay verdad avisada y no se inventa ninguna."""
    ev = _vela(motor, 6, [_cerrado(SIM, "SL", 5)])
    assert len(ev) == 1
    assert ev[0].acciones == pytest.approx(SIM)
    assert ev[0].posicion_total == pytest.approx(SIM)


def test_la_prealerta_no_consume_el_cuadre(motor):
    """Mirar sin marcar (prealerta) no puede gastar el «resto» del ultimo tramo:
    la salida de verdad, al cerrar la vela, tiene que salir igual."""
    _entrar(motor)
    trades = [_cerrado(SIM, "SL", 5)]
    motor._guion["trades"] = trades
    motor._guion["entrada_en"] = None
    motor.mirar_sin_marcar("MEDS", _frame(6), {})
    ev = _vela(motor, 6, trades)
    assert len(ev) == 1 and ev[0].acciones == 284.0
