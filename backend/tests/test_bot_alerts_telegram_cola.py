"""El envio a Telegram en segundo plano, con reintentos y en orden.

17-sep-2026, 14:31: un timeout de Telegram en el tramo 2 de KXIN se dio por
perdido sin reintento y dejo el bot parado 10 s. Estos tests fijan lo que
tiene que pasar en su lugar: encolar no espera, se reintenta con espera, un
rechazo 4xx no se reintenta, los mensajes salen en orden y `vaciar` espera a
que salga lo pendiente al cerrar.
"""
from __future__ import annotations

import threading
import time

import pytest

from app.services import bot_alerts_telegram as tg


@pytest.fixture(autouse=True)
def _telegram_encendido(monkeypatch):
    monkeypatch.setenv("BOT_ALERTS_TELEGRAM", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100")
    monkeypatch.setattr(tg, "ESPERA_REINTENTO", 0.0)
    monkeypatch.setattr(tg, "perdidos", 0)
    # cola limpia y sin hilo heredado de otro test
    monkeypatch.setattr(tg, "_cola", tg.queue.Queue())
    monkeypatch.setattr(tg, "_hilo_envio", None)
    yield


def _respuestas(secuencia):
    """Un `_post` falso que devuelve las respuestas dadas, en orden, y apunta
    cada intento."""
    intentos: list[str] = []
    cola = list(secuencia)

    def falso(texto):
        intentos.append(texto)
        return cola.pop(0) if cola else (True, False, "")

    return falso, intentos


def test_encolar_vuelve_al_instante_aunque_telegram_tarde(monkeypatch):
    lento = threading.Event()

    def post_lento(texto):
        lento.wait(2.0)
        return True, False, ""

    monkeypatch.setattr(tg, "_post", post_lento)
    t0 = time.perf_counter()
    assert tg.encolar("hola") is True
    assert time.perf_counter() - t0 < 0.2, "encolar no puede esperar a Telegram"
    lento.set()
    assert tg.vaciar(2.0) is True


def test_reintenta_tras_timeout_y_lo_deja_en_el_log(monkeypatch, caplog):
    falso, intentos = _respuestas([(False, True, "fallo de envio: timed out")])
    monkeypatch.setattr(tg, "_post", falso)
    with caplog.at_level("WARNING", logger="btt.bot_alerts.telegram"):
        assert tg.enviar_con_reintentos("kxin") is True
    assert len(intentos) == 2
    assert "enviado al intento 2" in caplog.text
    assert tg.perdidos == 0


def test_tres_fallos_lo_dan_por_perdido_y_lo_cuentan(monkeypatch, caplog):
    falso, intentos = _respuestas([(False, True, "timed out")] * 5)
    monkeypatch.setattr(tg, "_post", falso)
    with caplog.at_level("ERROR", logger="btt.bot_alerts.telegram"):
        assert tg.enviar_con_reintentos("kxin 394 de 787") is False
    assert len(intentos) == tg.REINTENTOS
    assert "PERDIDO tras 3" in caplog.text
    assert "kxin 394 de 787" in caplog.text, "el texto perdido queda en el log"
    assert tg.perdidos == 1


def test_un_rechazo_4xx_no_se_reintenta(monkeypatch):
    falso, intentos = _respuestas([(False, False, "rechazado (400): bad request")])
    monkeypatch.setattr(tg, "_post", falso)
    assert tg.enviar_con_reintentos("mal formado") is False
    assert len(intentos) == 1
    assert tg.perdidos == 1


def test_los_mensajes_salen_en_orden(monkeypatch):
    salidos: list[str] = []
    monkeypatch.setattr(tg, "_post", lambda t: (salidos.append(t), (True, False, ""))[1])
    for i in range(20):
        tg.encolar(f"m{i}")
    assert tg.vaciar(5.0) is True
    assert salidos == [f"m{i}" for i in range(20)]


def test_vaciar_espera_a_lo_pendiente(monkeypatch):
    salidos: list[str] = []

    def post_lento(texto):
        time.sleep(0.05)
        salidos.append(texto)
        return True, False, ""

    monkeypatch.setattr(tg, "_post", post_lento)
    for i in range(5):
        tg.encolar(f"m{i}")
    assert tg.pendientes_de_envio() > 0
    assert tg.vaciar(5.0) is True
    assert len(salidos) == 5
    assert tg.pendientes_de_envio() == 0


def test_apagado_no_encola_ni_arranca_hilo(monkeypatch):
    monkeypatch.setenv("BOT_ALERTS_TELEGRAM", "false")
    assert tg.encolar("nada") is False
    assert tg._hilo_envio is None
    assert tg.pendientes_de_envio() == 0


def test_enviar_texto_sigue_siendo_un_intento(monkeypatch):
    falso, intentos = _respuestas([(False, True, "timed out")])
    monkeypatch.setattr(tg, "_post", falso)
    assert tg.enviar_texto("sincrono") is False
    assert len(intentos) == 1
