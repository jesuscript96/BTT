"""GET /estado sale de memoria y nunca espera a la red.

LO QUE PASO (15-sep-2026). El bot sondea su estado cada 5 s con 8 s de
paciencia. /estado abria una conexion a users.duckdb en cada peticion y, cuando
la cache de 60 s de Telegram caducaba, llamaba a getMe (hasta 10 s) dentro de
la peticion. Con la pagina de Portfolio cargando curvas (se serializan en la
base) o Telegram lento, /estado tardaba mas de 8 s y el bot anotaba «no se pudo
leer el estado: timed out» — 22 veces ese dia, en racimos, con el backend
respondiendo en milisegundos al resto. Nada estaba caido.

LO QUE HAY QUE GARANTIZAR:
  1. Con la cache del estado caliente, /estado NO abre la base.
  2. /estado NO llama a Telegram en el hilo de la peticion: `probar_sin_esperar`
     devuelve al instante y refresca en un hilo aparte.
  3. Los fallos de Telegram se recuerdan TTL_FALLO segundos (no un hilo por
     peticion cuando Telegram esta caido); los exitos siguen valiendo 60 s.
"""
import threading
import time

import pytest

from app.routers import bot_alerts as router
from app.services import bot_alerts_service as bas
from app.services import bot_alerts_telegram as tg


# ── 1. la base solo si la cache esta fria ─────────────────────────────────
def test_estado_con_cache_caliente_no_abre_la_base(monkeypatch):
    monkeypatch.setattr(router, "_guard", lambda: None)
    monkeypatch.setattr(bas, "estado_cacheado",
                        lambda: {"vigilando": True, "latido_at": "2026-09-15 10:00:00",
                                 "tickers_seguidos": 3, "fuente": "websocket", "detalle": "RTH"})
    monkeypatch.setattr(bas, "version_estrategias", lambda: 7)
    monkeypatch.setattr(tg, "probar_sin_esperar", lambda: {"ok": True, "detalle": "listo", "enviando": True})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")

    def base_prohibida(*a, **k):
        raise AssertionError("/estado abrio la base con la cache caliente")
    monkeypatch.setattr(router, "get_user_db_connection", base_prohibida)

    r = router.leer_estado()
    assert r["vigilando"] is True and r["tickers_seguidos"] == 3
    assert r["estrategias_version"] == 7
    assert r["telegram"]["detalle"] == "listo"


def test_estado_con_cache_fria_lee_la_base_una_vez(monkeypatch):
    monkeypatch.setattr(router, "_guard", lambda: None)
    monkeypatch.setattr(bas, "estado_cacheado", lambda: None)
    monkeypatch.setattr(bas, "version_estrategias", lambda: 0)
    monkeypatch.setattr(tg, "probar_sin_esperar", lambda: {"ok": True})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")

    class Con:
        cerrada = False
        def close(self): self.cerrada = True
    con = Con()
    aperturas = []
    monkeypatch.setattr(router, "get_user_db_connection", lambda **k: (aperturas.append(1), con)[1])
    monkeypatch.setattr(bas, "get_estado", lambda c: {"vigilando": False, "latido_at": None})

    r = router.leer_estado()
    assert aperturas == [1] and con.cerrada
    assert r["vigilando"] is False


# ── 2. Telegram nunca en el camino de la peticion ─────────────────────────
@pytest.fixture
def telegram_limpio(monkeypatch):
    monkeypatch.setattr(tg, "_cache_probar", None)
    monkeypatch.setattr(tg, "_cache_fallo", None)
    monkeypatch.setattr(tg, "_refresco_en_curso", False)
    monkeypatch.setattr(tg, "_cfg", lambda: ("TOKEN", "-100"))
    monkeypatch.setattr(tg, "_verify", lambda: False)
    monkeypatch.setattr(tg, "envio_activo", lambda: True)
    monkeypatch.setattr(tg, "motivo_inactivo", lambda: "")
    return monkeypatch


class _Resp:
    status_code = 200
    def json(self): return {"result": {"username": "Alertas_btt_bot"}}


def test_probar_sin_esperar_no_bloquea_aunque_telegram_tarde(telegram_limpio):
    llamadas = []
    listo = threading.Event()

    def get_lento(*a, **k):
        llamadas.append(time.time())
        time.sleep(1.0)                      # Telegram «lento»
        listo.set()
        return _Resp()
    telegram_limpio.setattr(tg.httpx, "get", get_lento)

    t0 = time.time()
    r1 = tg.probar_sin_esperar()
    assert time.time() - t0 < 0.3, "la peticion espero a la red"
    assert r1["detalle"] == "comprobando…" and r1["enviando"] is True

    assert listo.wait(3.0), "el refresco de fondo no llego a llamar a Telegram"
    time.sleep(0.05)
    r2 = tg.probar_sin_esperar()
    assert r2["ok"] is True and r2["bot"] == "Alertas_btt_bot"
    assert len(llamadas) == 1, "una sola llamada de red para todo el TTL"


def test_una_cache_caducada_devuelve_lo_viejo_y_refresca_de_fondo(telegram_limpio):
    viejo = {"ok": True, "bot": "viejo", "detalle": "listo", "enviando": True}
    telegram_limpio.setattr(tg, "_cache_probar", (time.time() - tg.TTL_PROBAR - 1, viejo))
    llamadas = []
    telegram_limpio.setattr(tg.httpx, "get", lambda *a, **k: (llamadas.append(1), _Resp())[1])

    r = tg.probar_sin_esperar()
    assert r["bot"] == "viejo", "mientras refresca, se da lo ultimo que se supo"
    for _ in range(50):
        if tg._cache_probar and tg._cache_probar[1].get("bot") == "Alertas_btt_bot":
            break
        time.sleep(0.05)
    assert tg._cache_probar[1]["bot"] == "Alertas_btt_bot"
    assert len(llamadas) == 1


# ── 3. los fallos se recuerdan un rato ────────────────────────────────────
def test_los_fallos_se_cachean_y_no_lanzan_un_hilo_por_peticion(telegram_limpio):
    llamadas = []

    def get_roto(*a, **k):
        llamadas.append(1)
        raise ConnectionError("dns caido")
    telegram_limpio.setattr(tg.httpx, "get", get_roto)

    tg.probar_sin_esperar()                  # lanza el refresco
    for _ in range(50):
        if tg._cache_fallo is not None:
            break
        time.sleep(0.05)
    assert tg._cache_fallo is not None and "error de red" in tg._cache_fallo[1]["detalle"]

    for _ in range(20):                      # 20 peticiones seguidas, como la pagina
        r = tg.probar_sin_esperar()
        assert r["ok"] is False and "error de red" in r["detalle"]
    time.sleep(0.1)
    assert len(llamadas) == 1, "con el fallo cacheado no se vuelve a llamar"


def test_pasado_el_ttl_del_fallo_se_vuelve_a_intentar(telegram_limpio):
    telegram_limpio.setattr(tg, "_cache_fallo",
                            (time.time() - tg.TTL_FALLO - 1, {"ok": False, "detalle": "error de red: x"}))
    llamadas = []
    telegram_limpio.setattr(tg.httpx, "get", lambda *a, **k: (llamadas.append(1), _Resp())[1])

    r = tg.probar_sin_esperar()
    assert r["ok"] is False, "hasta que no llega el refresco se da el ultimo fallo"
    for _ in range(50):
        if tg._cache_probar is not None:
            break
        time.sleep(0.05)
    assert tg._cache_probar[1]["ok"] is True
    assert tg._cache_fallo is None
    assert len(llamadas) == 1


def test_sin_token_no_hay_hilo_ni_red(telegram_limpio):
    telegram_limpio.setattr(tg, "_cfg", lambda: ("", ""))
    telegram_limpio.setattr(tg.httpx, "get", lambda *a, **k: pytest.fail("no debia llamar"))
    r = tg.probar_sin_esperar()
    assert r["ok"] is False and "TELEGRAM_BOT_TOKEN" in r["detalle"]
