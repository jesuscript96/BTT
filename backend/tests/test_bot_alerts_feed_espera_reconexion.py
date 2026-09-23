"""El feed espera ESPERA_RECONEXION antes de volver a conectar, siempre.

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


@pytest.mark.parametrize("espera_env", [5.0, 20.0])
def test_espera_configurada_antes_de_cada_reconexion(monkeypatch, espera_env):
    monkeypatch.setenv("MASSIVE_BOT_API_KEY", "clave")
    monkeypatch.setattr(feed_mod, "ESPERA_RECONEXION", espera_env)
    monkeypatch.setattr(feed_mod.websockets, "connect", _ConexionQueFalla)
    esperas: list[float] = []

    async def sleep_falso(segundos):
        esperas.append(segundos)
        if len(esperas) >= 3:
            f._parar = True

    monkeypatch.setattr(feed_mod.asyncio, "sleep", sleep_falso)
    f = _feed()
    asyncio.run(f.correr())
    assert esperas[0] == espera_env, "la primera reconexion ya espera el minimo"
    assert all(e >= espera_env for e in esperas), esperas
    assert esperas[1] == min(espera_env * 2, feed_mod.ESPERA_RECONEXION_MAX), "sin aguantar un minuto, se dobla hasta el tope (no se martillea)"


def test_por_defecto_quince_segundos_y_tope_de_un_minuto():
    """23-sep-2026: de 5 a 15 s, y el ping aguanta 60 s.

    El 21-sep se bajo a 5 s porque el corte tipico duraba 1-2 s y la conexion
    sobrante era la DEL SOCIO, que ya no solia estar. El 23-sep aparecio el
    caso contrario: a las 14:05:32 Massive nos echo a NOSOTROS por ping
    timeout (1011) estando el bot saturado, y entonces la conexion zombi es la
    nuestra. Volver a los 5 s se solapa con ella, la cuenta se pasa del tope y
    Massive echa a otro — al socio. Las velas del hueco ya no se pierden:
    `al_reconectar` las recupera por REST desde el 22-sep.
    """
    assert feed_mod.ESPERA_RECONEXION == 15.0
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
