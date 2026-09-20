"""El bot avisa la reentrada cuando la señal SIGUE encendida tras un stop.

Desde el 2026-09-20 el simulador entra por NIVEL (fuera de posición y con la
condición cumplida, entra), no por flanco. El bot avisaba solo en el flanco
(apagada → encendida), así que una reentrada del simulador con la señal
encendida de continuo no se avisaba… y luego SÍ se avisaba su salida:
una posición fantasma para Jaume. Ahora la señal se rearma cuando la última
salida avisada dejó la posición a cero (o cuando no hay ninguna entrada
avisada hoy). Todo lo demás del aviso es igual que antes: el flanco sigue
avisando, una señal encendida con la posición viva sigue sin avisar, y con
`accept_reentries=False` no hay segunda entrada.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import bot_alerts_engine as mod

VENTANA = {"inicio": "04:00", "fin": "16:00"}


def _frame(n):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-09-17 06:30", periods=n, freq="1min"),
        "open": np.full(n, 10.0), "high": np.full(n, 10.0),
        "low": np.full(n, 10.0), "close": np.full(n, 10.0),
        "volume": np.full(n, 1000.0),
    })


def _trade(entry_idx, exit_idx, motivo="SL"):
    return {"entry_idx": entry_idx, "exit_idx": exit_idx, "size": 100.0,
            "exit_price": 11.0, "exit_reason": motivo, "status": "Closed"}


@pytest.fixture
def motor(monkeypatch):
    guion = {"trades": [], "entries": None, "reentradas": True}

    def falso_simulate(**kw):
        return {"trades": list(guion["trades"])}

    def falso_translate(frame, sdef, stats, compiled=None):
        n = len(frame)
        ent = guion["entries"]
        entries = np.zeros(n, dtype=bool) if ent is None else np.asarray(ent[:n], dtype=bool)
        return {"direction": "Short", "entries": entries,
                "accept_reentries": guion["reentradas"],
                "max_reentries": 2 if guion["reentradas"] else 0,
                "sl_stop": 0.05}

    monkeypatch.setattr(mod, "simulate", falso_simulate)
    monkeypatch.setattr(mod, "translate_strategy", falso_translate)
    monkeypatch.setattr(mod, "_kwargs_simulate", lambda *a, **k: {})
    m = mod.MotorAlertas([])
    m._guion = guion
    return m


EST = {
    "strategy_id": "s1", "name": "PM gap", "definition": {
        "risk_management": {"use_stop_loss": True, "stop_loss_mode": "Fixed",
                            "fixed_stop_loss_pct": 5,
                            "hard_stop": {"type": "Percentage", "value": 5}},
    },
    "compiled": None, "riesgo_usd": 300.0, "ventana": VENTANA,
}


def _vela(motor, n, trades):
    motor._guion["trades"] = trades
    return motor._procesar_estrategia("AEMD", _frame(n), {}, EST)


def _abierta(entry_idx, n):
    """La posición viva tal y como la emite el simulador sobre un frame de n
    velas: cierre sintético EOD en la última."""
    return _trade(entry_idx, n - 1, "EOD")


def _tipos(eventos):
    return [e.tipo for e in eventos]


def test_reentra_con_la_senal_encendida_de_continuo(motor):
    """Señal encendida desde la vela 1 hasta el final. Entra (flanco en 1),
    stop en la 3, y la vela 4 —con la señal aún encendida— tiene que avisar
    la reentrada, que es lo que el simulador hace ahora."""
    motor._guion["entries"] = [False] + [True] * 20
    # vela 1: flanco -> entrada
    assert _tipos(_vela(motor, 2, [])) == ["entrada"]
    # vela 2: en posicion (trade sintetico abierto hasta el borde) -> nada
    assert _vela(motor, 3, [_abierta(2, 3)]) == []
    # vela 3: salta el stop -> salida, y en la MISMA vela la reentrada: la
    # señal sigue encendida y el simulador sale en i y entra en i+1. ANTES
    # el bot callaba la entrada (no hay flanco) y luego avisaba su salida.
    ev = _vela(motor, 4, [_trade(2, 3, "SL")])
    assert _tipos(ev) == ["salida", "entrada"], "la reentrada con la señal viva no se avisaba"
    # vela 4: el simulador ya la tiene abierta -> nada, y no se repite el aviso
    assert _vela(motor, 5, [_trade(2, 3, "SL"), _abierta(4, 5)]) == []
    assert _vela(motor, 6, [_trade(2, 3, "SL"), _abierta(4, 6)]) == []


def test_sin_salida_avisada_no_se_rearma(motor):
    """Señal encendida de continuo y posición viva: como antes, un solo aviso."""
    motor._guion["entries"] = [False] + [True] * 20
    assert _tipos(_vela(motor, 2, [])) == ["entrada"]
    for n in (3, 4, 5, 6):
        assert _vela(motor, n, [_abierta(2, n)]) == []


def test_sin_reentradas_no_hay_segunda_entrada(motor):
    """`accept_reentries=False`: tras el stop, la señal viva no avisa nada,
    porque el simulador tampoco entra (cupo agotado)."""
    motor._guion["entries"] = [False] + [True] * 20
    motor._guion["reentradas"] = False
    assert _tipos(_vela(motor, 2, [])) == ["entrada"]
    assert _vela(motor, 3, [_abierta(2, 3)]) == []
    assert _tipos(_vela(motor, 4, [_trade(2, 3, "SL")])) == ["salida"]
    assert _vela(motor, 5, [_trade(2, 3, "SL")]) == []


def test_el_flanco_sigue_avisando_igual_que_antes(motor):
    """Señal que se apaga y se enciende: el aviso llega en el flanco, y en
    las velas de señal encendida con la posición viva no hay nada."""
    motor._guion["entries"] = [False, True, True, False, False, True, True, True]
    assert _tipos(_vela(motor, 2, [])) == ["entrada"]
    assert _vela(motor, 3, [_abierta(2, 3)]) == []
    assert _vela(motor, 4, [_abierta(2, 4)]) == []               # vela 3 apagada, dentro
    assert _tipos(_vela(motor, 5, [_trade(2, 4, "SL")])) == ["salida"]  # vela 4 apagada: no reentra
    assert _tipos(_vela(motor, 6, [_trade(2, 4, "SL")])) == ["entrada"]  # flanco en 5
