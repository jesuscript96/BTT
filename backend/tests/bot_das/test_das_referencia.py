"""Tests de `app.bot_das.referencia_massive` (§3.13; §10 fila test_das_referencia; riesgo 35; R-Q-01).

Todo con un `abrir` falso: ninguna petición sale a la red. Casos de §10:
caché por día (la segunda llamada no abre); `ficha` None si falla o el JSON es
raro; `splits_de_hoy` None si falla y el conjunto correcto con paginación; la
clave nunca aparece en la URL ni en el texto de los errores.
"""
from __future__ import annotations

import io
import json
import logging
import urllib.error
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import app.bot_das.referencia_massive as rm
from app.bot_das import tipos
from app.bot_das.referencia_massive import Ficha, Referencia

CLAVE = "clave-falsa-de-prueba-0000"   # no es una clave real
BASE = "https://api.massive.com"
HOY = date(2026, 9, 25)                 # el día del reloj simulado del conftest


class AbrirFalso:
    """Sustituto de `urllib.request.urlopen`: responde por URL (prefijo) y graba cada petición."""

    def __init__(self, respuestas: dict | None = None, error: Exception | None = None) -> None:
        self.respuestas = dict(respuestas or {})
        self.error = error
        self.peticiones: list = []
        self.timeouts: list = []
        self.cerradas = 0

    def __call__(self, peticion, timeout=None):
        self.peticiones.append(peticion)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        url = peticion.full_url
        for prefijo, cuerpo in self.respuestas.items():
            if url == prefijo or url.startswith(prefijo):
                if isinstance(cuerpo, Exception):
                    raise cuerpo
                datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode("utf-8")
                return _Respuesta(datos, self)
        raise urllib.error.URLError("sin respuesta preparada")

    @property
    def urls(self) -> list[str]:
        return [p.full_url for p in self.peticiones]


class _Respuesta(io.BytesIO):
    def __init__(self, datos: bytes, abrir: AbrirFalso) -> None:
        super().__init__(datos)
        self._abrir = abrir

    def close(self) -> None:
        self._abrir.cerradas += 1
        super().close()


FICHA_JSON = {"status": "OK", "results": {
    "ticker": "ABCD", "name": "Abcd Holdings Inc.", "type": "CS", "sic_code": "2834",
    "list_date": "2026-08-27", "market_cap": 12345678.9}}
URL_FICHA = f"{BASE}/v3/reference/tickers/ABCD"
URL_SPLITS = f"{BASE}/v3/reference/splits?execution_date=2026-09-25"


def referencia(dir_bot: Path, reloj, abrir, clave: str = CLAVE) -> Referencia:
    return Referencia(clave, dir_bot / "cache", reloj, timeout_s=2.5, abrir=abrir)


# ── ficha (R-A-03 v2, A12) ──────────────────────────────────────────────
def test_ficha_reexportada_de_tipos():
    assert Ficha is tipos.Ficha


def test_ficha_parseo(dir_bot, reloj):
    abrir = AbrirFalso({URL_FICHA: FICHA_JSON})
    ref = referencia(dir_bot, reloj, abrir)
    f = ref.ficha("abcd")
    assert f == Ficha(ticker="ABCD", list_date=date(2026, 8, 27), sic_code="2834", tipo="CS",
                      market_cap=Decimal("12345678.9"), nombre="Abcd Holdings Inc.")
    assert isinstance(f.market_cap, Decimal)
    assert abrir.timeouts == [2.5] and abrir.cerradas == 1


def test_ficha_campos_ausentes_o_raros(dir_bot, reloj):
    abrir = AbrirFalso({URL_FICHA: {"results": {"sic_code": 6770, "list_date": "no-fecha",
                                                 "market_cap": "NaN", "type": True}}})
    f = referencia(dir_bot, reloj, abrir).ficha("ABCD")
    assert f.sic_code == "6770"                  # R-A-03 v2: un SIC numérico se compara como texto
    assert f.list_date is None and f.market_cap is None and f.tipo is None and f.nombre == ""


def test_ficha_list_date_con_hora(dir_bot, reloj):
    abrir = AbrirFalso({URL_FICHA: {"results": {"list_date": "2026-09-01T00:00:00Z"}}})
    assert referencia(dir_bot, reloj, abrir).ficha("ABCD").list_date == date(2026, 9, 1)


def test_ficha_cache_por_dia(dir_bot, reloj):
    """§3.13: una ficha no cambia dentro del día; la segunda llamada NO abre red (tampoco otra instancia)."""
    abrir = AbrirFalso({URL_FICHA: FICHA_JSON})
    ref = referencia(dir_bot, reloj, abrir)
    primera = ref.ficha("ABCD")
    assert ref.ficha("ABCD") == primera and len(abrir.peticiones) == 1
    ruta = dir_bot / "cache" / "referencia_2026-09-25.json"
    assert ref.ruta_cache() == ruta and ruta.exists()
    # otra instancia el mismo día lee el fichero
    abrir2 = AbrirFalso(error=AssertionError("no debía abrir"))
    assert referencia(dir_bot, reloj, abrir2).ficha("ABCD") == primera
    assert abrir2.peticiones == []
    # al día siguiente se vuelve a preguntar y se escribe otro fichero
    reloj.avanzar(24 * 3600)
    assert ref.ficha("ABCD") == primera and len(abrir.peticiones) == 2
    assert (dir_bot / "cache" / "referencia_2026-09-26.json").exists()


@pytest.mark.parametrize("cuerpo", [
    b"<html>502 Bad Gateway</html>",
    b"\xff\xfe\x00",
    {"status": "OK"},
    {"results": []},
    {"results": None},
    ["ABCD"],
    "texto",
], ids=["A12-no-json", "A12-bytes-raros", "A12-sin-results", "A12-results-lista",
        "A12-results-none", "A12-lista", "A12-cadena"])
def test_ficha_json_raro_es_none_y_no_se_cachea(dir_bot, reloj, cuerpo):
    abrir = AbrirFalso({URL_FICHA: cuerpo})
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.ficha("ABCD") is None
    assert ref.ficha("ABCD") is None and len(abrir.peticiones) == 2   # A12: se reintenta
    assert ref.errores == 2 and ref.ultimo_error


@pytest.mark.parametrize("error", [
    urllib.error.URLError("timed out"),
    TimeoutError("lectura"),
    urllib.error.HTTPError(URL_FICHA, 404, "Not Found", {}, None),
    OSError("conexión rechazada"),
    RuntimeError("cualquier cosa"),
], ids=["A12-urlerror", "A12-timeout", "A12-http-404", "A12-oserror", "A12-otro"])
def test_ficha_fallo_de_red_es_none(dir_bot, reloj, error):
    abrir = AbrirFalso(error=error)
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.ficha("ABCD") is None
    assert ref.errores == 1 and type(error).__name__ in ref.ultimo_error


def test_ficha_ticker_vacio_no_abre(dir_bot, reloj):
    abrir = AbrirFalso()
    assert referencia(dir_bot, reloj, abrir).ficha("  ") is None
    assert abrir.peticiones == []


def test_ficha_ticker_se_escapa_en_la_url(dir_bot, reloj):
    abrir = AbrirFalso({f"{BASE}/v3/reference/tickers/BRK.B": {"results": {"name": "B"}}})
    assert referencia(dir_bot, reloj, abrir).ficha("brk.b").nombre == "B"
    abrir2 = AbrirFalso()
    referencia(dir_bot, reloj, abrir2).ficha("A/B?x")
    assert abrir2.urls == [f"{BASE}/v3/reference/tickers/A%2FB%3FX"]


def test_sin_clave_no_abre_y_avisa_una_vez(dir_bot, reloj):
    abrir = AbrirFalso({URL_FICHA: FICHA_JSON})
    ref = referencia(dir_bot, reloj, abrir, clave="  ")
    assert not ref.tiene_clave
    assert ref.ficha("ABCD") is None and ref.splits_de_hoy(HOY) is None and ref.ficha("ABCD") is None
    assert abrir.peticiones == [] and ref.errores == 1


def test_cache_corrupta_se_ignora(dir_bot, reloj):
    ruta = dir_bot / "cache" / "referencia_2026-09-25.json"
    ruta.write_text("{esto no es json", encoding="utf-8")
    abrir = AbrirFalso({URL_FICHA: FICHA_JSON})
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.ficha("ABCD").nombre == "Abcd Holdings Inc."
    assert json.loads(ruta.read_text(encoding="utf-8"))["fichas"]["ABCD"]["sic_code"] == "2834"


def test_cache_con_forma_rara_se_ignora(dir_bot, reloj):
    ruta = dir_bot / "cache" / "referencia_2026-09-25.json"
    ruta.write_text(json.dumps({"fichas": {"ABCD": "x"}, "splits": {"2026-09-25": "x"}}), encoding="utf-8")
    abrir = AbrirFalso({URL_FICHA: FICHA_JSON, URL_SPLITS: {"results": []}})
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.ficha("ABCD") is not None and ref.splits_de_hoy(HOY) == set()
    assert len(abrir.peticiones) == 2


def test_cache_no_escribible_no_tumba(dir_bot, reloj):
    abrir = AbrirFalso({URL_FICHA: FICHA_JSON})
    bloqueo = dir_bot / "no_es_dir"
    bloqueo.write_text("fichero", encoding="utf-8")
    ref = Referencia(CLAVE, bloqueo / "cache", reloj, abrir=abrir)
    assert ref.ficha("ABCD") is not None
    assert ref.ficha("ABCD") is not None and len(abrir.peticiones) == 1   # queda la caché de memoria


# ── splits_de_hoy (R-A-03 v2, corrección 17, riesgo 35) ─────────────────
def test_splits_una_pagina(dir_bot, reloj):
    abrir = AbrirFalso({URL_SPLITS: {"results": [
        {"ticker": "aaa", "execution_date": "2026-09-25", "split_from": 10, "split_to": 1},
        {"ticker": "BBB", "execution_date": "2026-09-25"},
        {"ticker": "OTRO", "execution_date": "2026-09-24"},      # otro día: no cuenta
        {"ticker": "", "execution_date": "2026-09-25"},
        "basura",
    ]}})
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.splits_de_hoy(HOY) == {"AAA", "BBB"}
    assert "limit=1000" in abrir.urls[0]


def test_splits_vacio_es_respuesta_real(dir_bot, reloj):
    abrir = AbrirFalso({URL_SPLITS: {"status": "OK", "results": []}})
    assert referencia(dir_bot, reloj, abrir).splits_de_hoy(HOY) == set()


def test_splits_paginacion(dir_bot, reloj):
    abrir = AbrirFalso({
        f"{BASE}/v3/reference/splits?cursor=P2": {"results": [{"ticker": "CCC"}]},
        f"{BASE}/v3/reference/splits?cursor=P1": {"results": [{"ticker": "BBB"}],
                                                   "next_url": f"{BASE}/v3/reference/splits?cursor=P2"},
        URL_SPLITS: {"results": [{"ticker": "AAA", "execution_date": "2026-09-25"}],
                     "next_url": f"{BASE}/v3/reference/splits?cursor=P1&apiKey=OTRA"},
    })
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.splits_de_hoy(HOY) == {"AAA", "BBB", "CCC"}
    assert len(abrir.peticiones) == 3
    assert abrir.urls[1] == f"{BASE}/v3/reference/splits?cursor=P1"   # el apiKey del next_url se quita
    # caché: la segunda llamada no abre; el resultado es una copia
    s = ref.splits_de_hoy(HOY)
    s.add("ZZZ")
    assert ref.splits_de_hoy(HOY) == {"AAA", "BBB", "CCC"} and len(abrir.peticiones) == 3


def test_splits_fallo_en_segunda_pagina_es_none(dir_bot, reloj):
    """Riesgo 35: una lista incompleta es «no se pudo» (None), nunca un conjunto parcial."""
    abrir = AbrirFalso({
        f"{BASE}/v3/reference/splits?cursor=P1": urllib.error.URLError("caída"),
        URL_SPLITS: {"results": [{"ticker": "AAA"}], "next_url": f"{BASE}/v3/reference/splits?cursor=P1"},
    })
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.splits_de_hoy(HOY) is None
    assert not (dir_bot / "cache" / "referencia_2026-09-25.json").exists()


@pytest.mark.parametrize("siguiente", ["https://otro-host.example/v3/reference/splits?cursor=P1",
                                       "ftp://api.massive.com/x", 42],
                         ids=["riesgo35-otro-host", "riesgo35-esquema", "riesgo35-no-texto"])
def test_splits_next_url_no_fiable_es_none(dir_bot, reloj, siguiente):
    abrir = AbrirFalso({URL_SPLITS: {"results": [{"ticker": "AAA"}], "next_url": siguiente}})
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.splits_de_hoy(HOY) is None
    assert len(abrir.peticiones) == 1                        # la clave no viaja a otro host


def test_splits_paginacion_sin_fin(dir_bot, reloj):
    abrir = AbrirFalso({f"{BASE}/v3/reference/splits": {"results": [],
                                                        "next_url": f"{BASE}/v3/reference/splits?cursor=X"}})
    assert referencia(dir_bot, reloj, abrir).splits_de_hoy(HOY) is None
    assert len(abrir.peticiones) == rm.PAGINAS_MAX


@pytest.mark.parametrize("cuerpo", [b"no json", ["x"], {"results": "x"}],
                         ids=["riesgo35-no-json", "riesgo35-lista", "riesgo35-results-texto"])
def test_splits_json_raro_es_none(dir_bot, reloj, cuerpo):
    abrir = AbrirFalso({URL_SPLITS: cuerpo})
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.splits_de_hoy(HOY) is None
    assert ref.splits_de_hoy(HOY) is None and len(abrir.peticiones) == 2   # no se cachea el fallo


def test_splits_results_null_es_vacio(dir_bot, reloj):
    abrir = AbrirFalso({URL_SPLITS: {"results": None}})
    assert referencia(dir_bot, reloj, abrir).splits_de_hoy(HOY) == set()


def test_splits_fallo_de_red_es_none(dir_bot, reloj):
    abrir = AbrirFalso(error=urllib.error.URLError("sin red"))
    assert referencia(dir_bot, reloj, abrir).splits_de_hoy(HOY) is None


def test_splits_cache_en_fichero(dir_bot, reloj):
    abrir = AbrirFalso({URL_SPLITS: {"results": [{"ticker": "AAA"}]}})
    referencia(dir_bot, reloj, abrir).splits_de_hoy(HOY)
    abrir2 = AbrirFalso(error=AssertionError("no debía abrir"))
    assert referencia(dir_bot, reloj, abrir2).splits_de_hoy(HOY) == {"AAA"}
    assert abrir2.peticiones == []


# ── la clave (R-Q-01, riesgo 20) ────────────────────────────────────────
def test_clave_solo_en_la_cabecera(dir_bot, reloj):
    abrir = AbrirFalso({URL_FICHA: FICHA_JSON, URL_SPLITS: {"results": []}})
    ref = referencia(dir_bot, reloj, abrir)
    ref.ficha("ABCD")
    ref.splits_de_hoy(HOY)
    assert len(abrir.peticiones) == 2
    for peticion in abrir.peticiones:
        assert CLAVE not in peticion.full_url
        assert "apikey" not in peticion.full_url.lower()
        assert peticion.get_header("Authorization") == f"Bearer {CLAVE}"
    cache = (dir_bot / "cache" / "referencia_2026-09-25.json").read_text(encoding="utf-8")
    assert CLAVE not in cache


def test_clave_nunca_en_errores_ni_log(dir_bot, reloj, caplog):
    error = urllib.error.URLError(f"fallo con Bearer {CLAVE} dentro")
    abrir = AbrirFalso(error=error)
    ref = referencia(dir_bot, reloj, abrir)
    with caplog.at_level(logging.DEBUG):
        assert ref.ficha("ABCD") is None
        assert ref.splits_de_hoy(HOY) is None
    assert CLAVE not in ref.ultimo_error and "***" in ref.ultimo_error
    assert CLAVE not in caplog.text
    assert "***" in caplog.text


def test_desde_env_lee_en_la_llamada(dir_bot, reloj, monkeypatch):
    abrir = AbrirFalso({URL_FICHA: FICHA_JSON})
    sin = Referencia.desde_env(dir_bot / "cache", reloj, abrir=abrir)
    assert not sin.tiene_clave and sin.ficha("ABCD") is None
    monkeypatch.setenv("MASSIVE_BOT_API_KEY", CLAVE)
    monkeypatch.setenv("MASSIVE_API_KEY", "otra-que-no-se-usa")
    con = Referencia.desde_env(dir_bot / "cache", reloj, abrir=abrir)
    assert con.tiene_clave and con.base_url == BASE
    assert con.ficha("ABCD") is not None
    assert abrir.peticiones[-1].get_header("Authorization") == f"Bearer {CLAVE}"


def test_desde_env_base_url(dir_bot, reloj, monkeypatch):
    monkeypatch.setenv("MASSIVE_BOT_API_KEY", CLAVE)
    monkeypatch.setenv("MASSIVE_API_BASE_URL", "https://espejo.example/")
    abrir = AbrirFalso({"https://espejo.example/v3/reference/tickers/ABCD": FICHA_JSON})
    ref = Referencia.desde_env(dir_bot / "cache", reloj, abrir=abrir)
    assert ref.base_url == "https://espejo.example" and ref.ficha("ABCD") is not None


def test_modulo_sin_websocket_ni_httpx():
    """R-A-06.4: REST con urllib; ningún websocket ni httpx (la fuga de tokens por el log)."""
    fuente = Path(rm.__file__).read_text(encoding="utf-8")
    for prohibido in ("import websocket", "from websocket", "import httpx", "from httpx"):
        assert prohibido not in fuente


# ── E1-07: la clave no sigue a una redirección a otro host ni viaja en claro ─
def _peticion_con_clave(url: str = f"{BASE}/v3/reference/tickers/ABCD"):
    import urllib.request
    return urllib.request.Request(url, headers={"Authorization": f"Bearer {CLAVE}"})


@pytest.mark.parametrize("destino", [
    "https://otro-host.example/v3/reference/tickers/ABCD",
    "http://api.massive.com/v3/reference/tickers/ABCD",
    "http://otro-host.example/x",
], ids=["E1-07-otro-host", "E1-07-https-a-http", "E1-07-otro-host-en-claro"])
def test_E1_07_redireccion_fuera_no_se_sigue(destino):
    """Un 302 de Massive (o de un proxy) a otro host o a http NO se sigue: urllib reenviaría la cabecera con la clave."""
    manejador = rm._RedireccionSegura()
    assert manejador.redirect_request(_peticion_con_clave(), None, 302, "Found", {}, destino) is None


@pytest.mark.parametrize("destino", [f"{BASE}/v3/reference/tickers/ABCD/", "/v3/reference/tickers/ABCD?x=1"],
                         ids=["E1-07-mismo-host-https", "E1-07-relativa-mismo-host"])
def test_E1_07_redireccion_al_mismo_host_https_si(destino):
    nueva = rm._RedireccionSegura().redirect_request(_peticion_con_clave(), None, 302, "Found", {}, destino)
    assert nueva is not None and nueva.full_url.startswith(BASE)


def test_E1_07_el_abrir_por_defecto_es_el_seguro(dir_bot, reloj):
    import inspect
    assert inspect.signature(Referencia.__init__).parameters["abrir"].default is rm.abrir_seguro
    assert inspect.signature(Referencia.desde_env).parameters["abrir"].default is rm.abrir_seguro
    opener_handlers = []

    class Espia:
        def __init__(self, *manejadores):
            opener_handlers.extend(manejadores)

        def open(self, peticion, timeout=None):
            raise urllib.error.URLError("sin red en los tests")

    import urllib.request
    original = urllib.request.build_opener
    try:
        urllib.request.build_opener = lambda *m: Espia(*m)
        ref = Referencia(CLAVE, dir_bot / "cache", reloj)
        assert ref.ficha("ABCD") is None
    finally:
        urllib.request.build_opener = original
    assert opener_handlers == [rm._RedireccionSegura]


@pytest.mark.parametrize("base", ["http://api.massive.com", "http://espejo.example/"],
                         ids=["E1-07-base-http", "E1-07-espejo-http"])
def test_E1_07_base_sin_https_no_envia_la_clave(dir_bot, reloj, base):
    abrir = AbrirFalso(error=AssertionError("no debía abrir"))
    ref = Referencia(CLAVE, dir_bot / "cache", reloj, abrir=abrir, base_url=base)
    assert ref.ficha("ABCD") is None and ref.splits_de_hoy(HOY) is None
    assert abrir.peticiones == [] and "https" in ref.ultimo_error and CLAVE not in ref.ultimo_error


def test_E1_07_next_url_en_claro_no_se_sigue(dir_bot, reloj):
    abrir = AbrirFalso({URL_SPLITS: {"results": [{"ticker": "AAA"}],
                                     "next_url": "http://api.massive.com/v3/reference/splits?cursor=P1"}})
    assert referencia(dir_bot, reloj, abrir).splits_de_hoy(HOY) is None
    assert len(abrir.peticiones) == 1


# ── G1A-03 / G1B-08: caché de solo lectura para el decisor ───────────────
def test_G1A_03_ficha_en_cache_nunca_abre_red(dir_bot, reloj):
    """El decisor solo consulta la caché: sin ficha → None (A12) y queda pedida; la precarga la trae."""
    abrir = AbrirFalso({URL_FICHA: FICHA_JSON})
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.ficha_en_cache("abcd") is None and abrir.peticiones == []
    assert ref.tomar_pendientes() == ["ABCD"]
    assert ref.precargar_ficha("ABCD") is not None and len(abrir.peticiones) == 1
    assert ref.ficha_en_cache("ABCD").ticker == "ABCD" and len(abrir.peticiones) == 1
    assert ref.tomar_pendientes() == []


def test_G1A_03_pedir_ficha_al_ver_el_radar(dir_bot, reloj):
    ref = referencia(dir_bot, reloj, AbrirFalso({URL_FICHA: FICHA_JSON}))
    ref.pedir_ficha(" abcd ")
    ref.pedir_ficha("")
    assert ref.tomar_pendientes() == ["ABCD"]


def test_G1A_03_una_ficha_fallida_no_se_repide_antes_de_60s(dir_bot, reloj):
    abrir = AbrirFalso(error=urllib.error.URLError("caída"))
    ref = referencia(dir_bot, reloj, abrir)
    ref.ficha_en_cache("ABCD")
    assert ref.precargar_ficha("ABCD") is None
    assert ref.tomar_pendientes() == []
    reloj.avanzar(rm.REINTENTO_FICHA_S)
    assert ref.tomar_pendientes() == ["ABCD"]


def test_G1A_03_splits_en_cache_sin_red(dir_bot, reloj):
    abrir = AbrirFalso({URL_SPLITS: {"results": [{"ticker": "AAA"}]}})
    ref = referencia(dir_bot, reloj, abrir)
    assert ref.splits_en_cache(HOY) is None and ref.splits_pendientes(HOY) is True and abrir.peticiones == []
    assert ref.precargar_splits(HOY) == {"AAA"}
    s = ref.splits_en_cache(HOY)
    s.add("ZZZ")                                                    # copia: la caché no cambia
    assert ref.splits_en_cache(HOY) == {"AAA"} and ref.splits_pendientes(HOY) is False
    fallo = referencia(dir_bot / "otro", reloj, AbrirFalso(error=urllib.error.URLError("caída")))
    assert fallo.precargar_splits(HOY) is None
    assert fallo.splits_en_cache(HOY) is None and fallo.splits_pendientes(HOY) is False   # falló: avisar, no esperar


def test_G1A_03_la_lectura_no_espera_a_una_precarga_lenta(dir_bot, reloj):
    """Una Referencia cuya red tarda (8 s en la vida real) no puede frenar al decisor: la red va SIN el lock."""
    import threading
    import time as _time
    dentro, soltar = threading.Event(), threading.Event()

    def abrir_lento(peticion, timeout=None):
        dentro.set()
        soltar.wait(5.0)
        return _Respuesta(json.dumps(FICHA_JSON).encode("utf-8"), AbrirFalso())

    ref = referencia(dir_bot, reloj, abrir_lento)
    hilo = threading.Thread(target=ref.precargar_ficha, args=("ABCD",), daemon=True)
    hilo.start()
    assert dentro.wait(2.0)
    inicio = _time.perf_counter()
    for _ in range(100):
        assert ref.ficha_en_cache("OTRA") is None
        ref.splits_en_cache(HOY)
    assert _time.perf_counter() - inicio < 0.5                     # milisegundos, con la precarga bloqueada en la red
    soltar.set()
    hilo.join(5.0)
    assert ref.ficha_en_cache("ABCD") is not None
