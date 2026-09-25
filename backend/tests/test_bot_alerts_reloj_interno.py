"""El reloj interno del lector (24-sep-2026).

`hueco_lectura` no distingue entre «el bucle estaba atascado» y «Massive no
mandaba nada». El pulso lo distingue: se despierta cada 0,1 s en el mismo bucle
que lee, asi que si el bucle se bloquea, el pulso llega tarde; si el bucle esta
libre esperando datos, llega a su hora. Estas pruebas fijan las dos mitades.
"""
import asyncio
import time

from app.services.bot_alerts_feed import FeedEnVivo


def _feed():
    return FeedEnVivo([], lambda *a, **k: None)


def test_si_el_bucle_se_bloquea_el_reloj_lo_ve():
    """Un calculo que no suelta el bucle 0,6 s tiene que aparecer como ~0,6 s de
    retraso: es el caso «el atasco es nuestro»."""
    f = _feed()

    async def escena():
        pulso = asyncio.get_event_loop().create_task(f._pulso())
        await asyncio.sleep(0.3)          # el pulso arranca y late normal
        time.sleep(0.6)                   # bloqueo: nada del bucle puede correr
        await asyncio.sleep(0.3)          # el pulso se despierta y lo mide
        f.parar()
        await pulso

    asyncio.run(escena())
    assert f.retraso_bucle >= 0.45, f"el bloqueo de 0,6 s no se vio: {f.retraso_bucle:.2f} s"


def test_si_el_bucle_solo_espera_el_reloj_va_en_hora():
    """Esperar datos que no llegan NO es un atasco: el bucle esta libre y el
    pulso late a su hora. Es el caso «el retraso es de Massive»."""
    f = _feed()

    async def escena():
        pulso = asyncio.get_event_loop().create_task(f._pulso())
        await asyncio.sleep(1.5)          # un «hueco» sin datos, bucle libre
        f.parar()
        await pulso

    asyncio.run(escena())
    assert f.retraso_bucle < 0.2, f"con el bucle libre marco {f.retraso_bucle:.2f} s de retraso"


def test_el_reloj_se_para_con_el_feed():
    f = _feed()

    async def escena():
        pulso = asyncio.get_event_loop().create_task(f._pulso())
        await asyncio.sleep(0.25)
        f.parar()
        await asyncio.wait_for(pulso, timeout=2.0)

    asyncio.run(escena())      # si no se parara, wait_for reventaria
