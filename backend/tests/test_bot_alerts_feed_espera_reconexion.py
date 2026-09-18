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


@pytest.mark.parametrize("espera_env", [60.0, 5.0])
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
    assert esperas[1] == espera_env * 2, "sin aguantar un minuto, se dobla (no se martillea)"


def test_por_defecto_es_un_minuto():
    assert feed_mod.ESPERA_RECONEXION == 60.0
