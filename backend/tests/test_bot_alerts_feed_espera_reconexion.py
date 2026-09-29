"""El feed espera antes de volver a conectar, siempre (escalera desde el 29-sep).

18-sep-2026: la cuenta de Massive la comparten dos claves; reconectar al
segundo tras un corte sucio suma una conexion de mas y Massive echa a otro
cliente (asi nos tiraba el Docker del socio). Jaume: «un delay de 1 minuto
para cualquier reconexion».
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import bot_alerts_feed as feed_mod


class _ConexionQueFalla:
    """Sustituye a websockets.connect: entrar en el `async with` revienta."""

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        raise OSError("cable fuera")

    async def __aexit__(self, *a):
        return False


def _feed():
    return feed_mod.FeedEnVivo(["AAA"], al_cerrar_vela=lambda *a, **k: None)


def _esperas_con_rechazos(monkeypatch, n: int) -> list[float]:
    """Massive nos rechaza `n` veces seguidas: las esperas que hace el feed."""
    monkeypatch.setenv("MASSIVE_BOT_API_KEY", "clave")
    monkeypatch.setattr(feed_mod.websockets, "connect", _ConexionQueFalla)
    esperas: list[float] = []

    async def sleep_falso(segundos):
        esperas.append(segundos)
        if len(esperas) >= n:
            f._parar = True

    monkeypatch.setattr(feed_mod.asyncio, "sleep", sleep_falso)
    f = _feed()
    asyncio.run(f.correr())
    return esperas


def test_la_escalera_sube_un_peldano_por_rechazo_y_se_queda_en_el_ultimo(monkeypatch):
    """29-sep-2026. Sin aguantar un minuto conectados (la cuenta sigue llena),
    cada reintento espera el peldaño siguiente; no se martillea."""
    esperas = _esperas_con_rechazos(monkeypatch, 7)
    assert esperas == [3.0, 5.0, 15.0, 30.0, 60.0, 60.0, 60.0]


def test_escalera_configurable(monkeypatch):
    monkeypatch.setattr(feed_mod, "ESCALERA_RECONEXION", (2.0, 10.0))
    assert _esperas_con_rechazos(monkeypatch, 3) == [2.0, 10.0, 10.0]


def test_por_defecto_tres_segundos_y_tope_de_un_minuto():
    """29-sep-2026, Jaume: «15 segundos es mucho si el problema no es nuestro».

    Ese dia, 1008 a las 10:03:39 con el bot conectado desde las 09:41: la
    conexion de mas no era nuestra y los 15 s fijos (23-sep) eran hueco puro.
    El primer reintento va a los 3 s; si Massive nos vuelve a echar, sube la
    escalera 5 → 15 → 30 → 60, que es lo que protegia el 15 fijo: no solaparnos
    con una zombi (nuestra o del socio) y echar a otro de la cuenta.
    """
    assert feed_mod.ESCALERA_RECONEXION == (3.0, 5.0, 15.0, 30.0, 60.0)
    assert feed_mod.ESPERA_RECONEXION == 3.0
    assert feed_mod.ESPERA_RECONEXION_MAX == 60.0


class _WsQueCae:
    """Primera conexion: cae al leer. Segunda: vive hasta que el feed pare."""
    intentos = 0

    def __init__(self, *a, **k):
        _WsQueCae.intentos += 1
        self.n = _WsQueCae.intentos

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, *_):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.n == 1:
            raise OSError("nos han echado")
        await asyncio.sleep(0)
        return '{"ev":"status","status":"x","message":"y"}'


def test_tras_reconectar_avisa_con_los_segundos_sin_datos(monkeypatch):
    monkeypatch.setenv("MASSIVE_BOT_API_KEY", "clave")
    monkeypatch.setattr(feed_mod.websockets, "connect", _WsQueCae)
    _WsQueCae.intentos = 0
    reloj = {"t": 1000.0}
    monkeypatch.setattr(feed_mod.time, "time", lambda: reloj["t"])

    async def sleep_falso(segundos):
        reloj["t"] += segundos

    monkeypatch.setattr(feed_mod.asyncio, "sleep", sleep_falso)
    avisos = []
    f = feed_mod.FeedEnVivo(["AAA"], al_cerrar_vela=lambda *a, **k: None,
                            al_reconectar=lambda sin_datos: (avisos.append(sin_datos), setattr(f, "_parar", True)))
    asyncio.run(f.correr())
    assert f.reconexiones == 1
    assert avisos and abs(avisos[0] - feed_mod.ESPERA_RECONEXION) < 1e-6, "los segundos sin datos = la espera antes de volver"
