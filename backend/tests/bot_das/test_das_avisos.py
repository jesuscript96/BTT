"""Tests de `app.bot_das.avisos` (§10 fila `test_das_avisos.py`; R-M-01, R-M-02, R-M-05, R-J-08, R-Q-01, riesgo 20).

Sin red real: Telegram contra un `http.server` local en hilo; SMTP con un
`smtplib.SMTP` falso; SMS con el proveedor nulo. Las colas se paran siempre
en el `finally` de su fixture. Ningún valor secreto es real.
"""
from __future__ import annotations

import http.server
import json
import logging
import smtplib
import socket
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterator

import pytest

from app.bot_das import avisos
from app.bot_das.avisos import (
    MASCARA,
    NIVELES_CORREO,
    NIVELES_GRUPO_A,
    NIVELES_SMS,
    NIVELES_TODOS,
    Canal,
    CanalCorreo,
    CanalSMS,
    CanalTelegram,
    ColaAvisos,
    FiltroSecretos,
    HandlerFicheroDiario,
    ProveedorSMSNulo,
    aviso_de,
    canales_desde_env,
    con_prefijo_fase,
    desinstalar_logging,
    formatear_precio,
    instalar_logging,
    prefijo_fase,
    recortar_telegram,
    ruta_log,
    secretos_desde_env,
    texto_fill,
    texto_grupo_a,
    texto_rechazo,
    ultimas_lineas_log,
    unidades_utf16,
)
from app.bot_das.tipos import (
    Avisar,
    Aviso,
    EstadoLote,
    EstadoTicker,
    Fase,
    Fill,
    Grupo,
    Lado,
    Lote,
    Nivel,
    Orden,
    Origen,
    PosicionTicker,
    Proposito,
    TipoOrden,
)

BACKEND = Path(__file__).resolve().parents[2]
LOGGER_AVISOS = "btt.bot_das.avisos"

# Valores de PRUEBA con la forma de los reales (ninguno es una credencial).
TOKEN_PRUEBA = "123456789:AAprueba-falso_NO_real"
CHAT_PRUEBA = "-1001234567890"
CLAVE_DAS_PRUEBA = "claveDASdePrueba77"
CLAVE_SMTP_PRUEBA = "claveSMTPdePrueba88"


# ── utilidades ──────────────────────────────────────────────────────────
def aviso(nivel=Nivel.INFO, grupo=Grupo.B, texto="texto", clave=None) -> Aviso:
    return Aviso(nivel=nivel, grupo=grupo, texto=texto, clave=clave, creado_en=0.0)


def esperar(condicion: Callable[[], bool], limite_s: float = 5.0) -> bool:
    """Espera activa corta (10 ms) hasta que `condicion` sea cierta o pase `limite_s`."""
    fin = time.monotonic() + limite_s
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.01)
    return condicion()


class CanalGrabador:
    """Canal falso: graba lo que recibe; falla los `fallos` primeros intentos; o lanza si `lanza`."""

    def __init__(self, nombre: str, niveles=NIVELES_TODOS, grupos=frozenset({Grupo.B}), fallos: int = 0,
                 lanza: bool = False) -> None:
        self.nombre = nombre
        self.niveles = frozenset(niveles)
        self.grupos = frozenset(grupos)
        self.recibidos: list[str] = []
        self.intentos = 0
        self._fallos = fallos
        self._lanza = lanza
        self._cerrojo = threading.Lock()

    def enviar(self, texto: str) -> bool:
        with self._cerrojo:
            self.intentos += 1
            if self._lanza:
                raise RuntimeError("canal roto a propósito")
            if self.intentos <= self._fallos:
                return False
            self.recibidos.append(texto)
            return True


class CanalLento(CanalGrabador):
    """Canal que tarda hasta 2 s en cada envío (se libera en la limpieza para no alargar el test)."""

    def __init__(self) -> None:
        super().__init__("lento")
        self.empezado = threading.Event()
        self.liberar = threading.Event()

    def enviar(self, texto: str) -> bool:
        self.empezado.set()
        self.liberar.wait(2.0)
        return super().enviar(texto)


@pytest.fixture
def hacer_cola() -> Iterator[Callable[..., ColaAvisos]]:
    """Fábrica de colas; todas se paran al terminar el test (sin hilos colgando)."""
    creadas: list[ColaAvisos] = []

    def fabrica(canales, reloj=None, **kw) -> ColaAvisos:
        from app.bot_das.reloj import Reloj
        cola = ColaAvisos(canales, reloj if reloj is not None else Reloj(), **kw)
        creadas.append(cola)
        return cola

    try:
        yield fabrica
    finally:
        for cola in creadas:
            cola.parar(5.0)


class ListaHandler(logging.Handler):
    """Handler de prueba: guarda el texto YA FORMATEADO (lo que acabaría en el fichero)."""

    def __init__(self) -> None:
        super().__init__()
        self.lineas: list[str] = []
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self.lineas.append(self.format(record))


@pytest.fixture
def log_filtrado() -> Iterator[tuple[logging.Logger, ListaHandler]]:
    """Logger aislado con un handler que lleva `FiltroSecretos` (token de Telegram y clave de DAS)."""
    registro = logging.getLogger("prueba.bot_das.filtro")
    handler = ListaHandler()
    handler.addFilter(FiltroSecretos([TOKEN_PRUEBA, CLAVE_DAS_PRUEBA]))
    registro.addHandler(handler)
    registro.setLevel(logging.DEBUG)
    registro.propagate = False
    try:
        yield registro, handler
    finally:
        registro.removeHandler(handler)
        registro.propagate = True


# ── ColaAvisos: no bloquea (R-M-05) ─────────────────────────────────────
def test_poner_no_bloquea_con_canal_lento_R_M_05(hacer_cola):
    lento = CanalLento()
    cola = hacer_cola([lento])
    cola.arrancar()
    try:
        cola.poner(aviso(texto="primero"))
        assert lento.empezado.wait(2.0), "el hilo de envío no llegó al canal"
        tiempos = []
        for i in range(200):
            t0 = time.perf_counter()
            cola.poner(aviso(texto=f"aviso {i}"))
            tiempos.append(time.perf_counter() - t0)
        assert statistics.median(tiempos) < 0.001, f"mediana {statistics.median(tiempos) * 1000:.3f} ms"
        assert max(tiempos) < 0.05
        assert cola.pendientes == 200
    finally:
        lento.liberar.set()


def test_orden_conservado_R_J_08(hacer_cola):
    canal = CanalGrabador("tg")
    cola = hacer_cola([canal])
    textos = [f"aviso {i:03d}" for i in range(60)]
    for texto in textos:
        cola.poner(aviso(texto=texto))
    cola.arrancar()
    assert esperar(lambda: len(canal.recibidos) == 60)
    assert canal.recibidos == textos
    cola.parar(5.0)
    assert not cola.vivo


def test_vivo_y_parar(hacer_cola):
    cola = hacer_cola([CanalGrabador("tg")])
    assert not cola.vivo
    cola.arrancar()
    assert cola.vivo
    cola.parar(5.0)
    assert not cola.vivo


# ── reintentos (R-J-08) ─────────────────────────────────────────────────
def test_reintentos_hasta_que_sale_R_J_08(hacer_cola, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_AVISOS)
    canal = CanalGrabador("tg", fallos=2)
    cola = hacer_cola([canal], reintentos=3, espera_reintento_s=0.01)
    cola.poner(aviso(texto="insiste"))
    cola.arrancar()
    assert esperar(lambda: cola.enviados == 1)
    assert canal.intentos == 3
    assert canal.recibidos == ["insiste"]
    assert cola.fallidos == 0
    assert "enviado al intento 3" in caplog.text


def test_reintentos_agotados_cuenta_fallido_y_queda_en_log_R_J_08(hacer_cola, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_AVISOS)
    canal = CanalGrabador("tg", fallos=99)
    cola = hacer_cola([canal], reintentos=2, espera_reintento_s=0.01)
    cola.poner(aviso(texto="no sale"))
    cola.arrancar()
    assert esperar(lambda: cola.fallidos == 1)
    assert canal.intentos == 3                  # 1 + reintentos
    assert cola.enviados == 0
    assert "PERDIDO en tg tras 3 intento(s): no sale" in caplog.text


def test_canal_que_lanza_no_mata_el_hilo_R_J_08(hacer_cola):
    roto = CanalGrabador("roto", lanza=True)
    bueno = CanalGrabador("bueno")
    cola = hacer_cola([roto, bueno], reintentos=1, espera_reintento_s=0.0)
    cola.poner(aviso(texto="uno"))
    cola.poner(aviso(texto="dos"))
    cola.arrancar()
    assert esperar(lambda: bueno.recibidos == ["uno", "dos"])
    assert roto.intentos == 4                   # 2 avisos × (1 + 1 reintento)
    assert cola.fallidos == 2
    assert cola.vivo


def test_parar_vacia_con_un_intento_y_sin_esperas_seccion_6_2(hacer_cola):
    canal = CanalGrabador("caido", fallos=10_000)
    cola = hacer_cola([canal], reintentos=3, espera_reintento_s=10.0)
    for i in range(3):
        cola.poner(aviso(texto=f"a{i}"))
    cola.arrancar()
    assert esperar(lambda: canal.intentos >= 1)
    t0 = time.monotonic()
    cola.parar(5.0)
    assert time.monotonic() - t0 < 2.0          # no espera los 10 s de reintento
    assert cola.pendientes == 0
    assert cola.fallidos == 3
    assert canal.intentos in (3, 4)             # el primero pudo intentar 2 veces si ya estaba esperando
    assert not cola.vivo


# ── dedupe y tope ───────────────────────────────────────────────────────
@pytest.mark.parametrize(("avance_s", "entra"), [
    pytest.param(0, False, id="R-J-08-dedupe-misma-clave-al-instante"),
    pytest.param(59, False, id="R-J-08-dedupe-dentro-de-60s"),
    pytest.param(60, True, id="R-J-08-dedupe-caduca-a-los-60s"),
    pytest.param(3600, True, id="R-J-08-dedupe-mucho-despues"),
])
def test_dedupe_por_clave_y_ventana(hacer_cola, reloj, avance_s, entra):
    cola = hacer_cola([CanalGrabador("tg")], reloj=reloj)
    cola.poner(aviso(clave="stop-ABC"))
    reloj.avanzar(avance_s)
    cola.poner(aviso(clave="stop-ABC"))
    assert cola.pendientes == (2 if entra else 1)
    assert cola.deduplicados == (0 if entra else 1)


def test_dedupe_no_refresca_la_ventana_y_claves_distintas_pasan(hacer_cola, reloj):
    cola = hacer_cola([CanalGrabador("tg")], reloj=reloj)
    cola.poner(aviso(clave="k"))
    reloj.avanzar(40)
    cola.poner(aviso(clave="k"))                # deduplicado: NO mueve el inicio de la ventana
    reloj.avanzar(20)
    cola.poner(aviso(clave="k"))                # 60 s desde el primero → entra
    cola.poner(aviso(clave="otra"))
    cola.poner(aviso(clave=None))
    cola.poner(aviso(clave=None))               # sin clave nunca se deduplica
    assert cola.pendientes == 5
    assert cola.deduplicados == 1


def test_tope_cuenta_perdidos_y_avisa_una_vez_R_J_08(hacer_cola, caplog):
    caplog.set_level(logging.ERROR, logger=LOGGER_AVISOS)
    cola = hacer_cola([CanalGrabador("tg")], tope=3)
    for i in range(6):
        cola.poner(aviso(texto=str(i)))
    assert cola.pendientes == 3
    assert cola.perdidos == 3
    assert caplog.text.count("cola llena") == 1


def test_aviso_perdido_por_tope_no_registra_su_clave(hacer_cola, reloj):
    canal = CanalGrabador("tg")
    cola = hacer_cola([canal], reloj=reloj, tope=1)
    cola.poner(aviso(texto="llena"))
    cola.poner(aviso(texto="perdido", clave="k"))
    assert cola.perdidos == 1
    cola.arrancar()
    assert esperar(lambda: cola.pendientes == 0 and canal.recibidos == ["llena"])
    cola.poner(aviso(texto="ahora sí", clave="k"))   # misma clave, mismo instante: NO se calla
    assert esperar(lambda: canal.recibidos == ["llena", "ahora sí"])
    assert cola.deduplicados == 0


# ── enrutado por nivel y grupo (R-M-02, R-M-05) ─────────────────────────
@pytest.mark.parametrize(("nivel", "grupo", "esperados"), [
    pytest.param(Nivel.INFO, Grupo.B, {"tg-B"}, id="R-M-02-nivel1-solo-telegram"),
    pytest.param(Nivel.AVISO, Grupo.B, {"tg-B", "correo"}, id="R-M-02-nivel2-telegram-y-correo"),
    pytest.param(Nivel.MAXIMO, Grupo.B, {"tg-B", "correo", "sms"}, id="R-M-02-nivel3-telegram-correo-y-sms"),
    pytest.param(Nivel.INFO, Grupo.A, {"tg-A"}, id="R-M-05-grupo-A-solo-su-canal"),
    pytest.param(Nivel.MAXIMO, Grupo.A, set(), id="R-M-05-grupo-A-no-recibe-incidentes"),
])
def test_enrutado_por_nivel_y_grupo(hacer_cola, nivel, grupo, esperados):
    canales = [
        CanalGrabador("tg-B", NIVELES_TODOS, {Grupo.B}),
        CanalGrabador("correo", NIVELES_CORREO, {Grupo.B}),
        CanalGrabador("sms", NIVELES_SMS, {Grupo.B}),
        CanalGrabador("tg-A", NIVELES_GRUPO_A, {Grupo.A}),
    ]
    cola = hacer_cola(canales)
    cola.poner(aviso(nivel=nivel, grupo=grupo, texto="x"))
    cola.arrancar()
    assert esperar(lambda: cola.foto()["despachados"] == 1)
    cola.parar(5.0)
    assert {c.nombre for c in canales if c.recibidos} == esperados
    assert cola.enviados == len(esperados)


def test_todo_aviso_va_al_log_R_M_01(hacer_cola, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_AVISOS)
    cola = hacer_cola([])                      # sin canales: el log es lo único que queda (R-J-08)
    cola.poner(aviso(nivel=Nivel.MAXIMO, texto="posición sin stop"))
    cola.arrancar()
    assert esperar(lambda: cola.foto()["despachados"] == 1)
    registros = [r for r in caplog.records if "posición sin stop" in r.getMessage()]
    assert registros and registros[0].levelno == logging.ERROR
    assert "[AVISO 3/B]" in registros[0].getMessage()


def test_poner_normaliza_nivel_y_grupo_y_rechaza_basura(hacer_cola):
    canal = CanalGrabador("tg", NIVELES_CORREO)
    cola = hacer_cola([canal])
    cola.poner(Aviso(nivel=2, grupo="B", texto="entero y letra", clave=None, creado_en=0.0))
    cola.arrancar()
    assert esperar(lambda: canal.recibidos == ["entero y letra"])
    with pytest.raises(TypeError):
        cola.poner("no soy un aviso")
    with pytest.raises(ValueError):
        cola.poner(Aviso(nivel=7, grupo=Grupo.B, texto="x", clave=None, creado_en=0.0))
    with pytest.raises(ValueError):
        cola.poner(Aviso(nivel=Nivel.INFO, grupo="C", texto="x", clave=None, creado_en=0.0))


@pytest.mark.parametrize("kw", [
    pytest.param({"tope": 0}, id="tope-cero"),
    pytest.param({"tope": 1.5}, id="tope-no-entero"),
    pytest.param({"reintentos": -1}, id="reintentos-negativos"),
    pytest.param({"espera_reintento_s": -1.0}, id="espera-negativa"),
])
def test_cola_valida_parametros(kw):
    from app.bot_das.reloj import Reloj
    with pytest.raises(ValueError):
        ColaAvisos([], Reloj(), **kw)


def test_cola_rechaza_un_canal_sin_contrato():
    from app.bot_das.reloj import Reloj

    class SinEnviar:
        nombre = "x"
        niveles = NIVELES_TODOS
        grupos = frozenset({Grupo.B})

    with pytest.raises(TypeError):
        ColaAvisos([SinEnviar()], Reloj())


def test_foto_y_aviso_de():
    from app.bot_das.reloj import Reloj
    cola = ColaAvisos([CanalGrabador("tg")], Reloj())
    foto = cola.foto()
    assert set(foto) == {"pendientes", "perdidos", "deduplicados", "enviados", "fallidos", "despachados", "vivo", "canales"}
    assert foto["canales"] == ["tg"]
    hecho = aviso_de(Avisar(Nivel.AVISO, Grupo.B, "hola", clave="k"), 12.5)
    assert hecho == Aviso(nivel=Nivel.AVISO, grupo=Grupo.B, texto="hola", clave="k", creado_en=12.5)


# ── canales_desde_env (R-Q-01, R-M-02, R-M-05) ──────────────────────────
def _nombres(canales) -> list[str]:
    return [c.nombre for c in canales]


def test_canales_sin_nada_en_el_entorno_no_lanza_y_avisa(cfg, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_AVISOS)
    canales = canales_desde_env(cfg)
    assert _nombres(canales) == ["sms-nulo"]
    assert "TELEGRAM_BOT_TOKEN_B" in caplog.text


def test_canales_grupo_b_y_grupo_a_segun_interruptor(cfg, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_B", TOKEN_PRUEBA)
    monkeypatch.setenv("TELEGRAM_CHAT_ID_B", CHAT_PRUEBA)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_A", "555555:AAotro-falso")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_A", "-1009999")
    apagado = canales_desde_env(cfg)            # alertas_grupo_a.activo = false en la fixture
    assert _nombres(apagado) == ["telegram-B", "sms-nulo"]
    tg_b = apagado[0]
    assert tg_b.niveles == NIVELES_TODOS and tg_b.grupos == frozenset({Grupo.B})
    encendido = canales_desde_env(replace(cfg, alertas_grupo_a={**cfg.alertas_grupo_a, "activo": True}))
    assert _nombres(encendido) == ["telegram-B", "telegram-A", "sms-nulo"]
    tg_a = encendido[1]
    assert tg_a.niveles == frozenset({Nivel.INFO}) and tg_a.grupos == frozenset({Grupo.A})


def test_canales_grupo_a_activo_sin_credenciales(cfg, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_AVISOS)
    canales = canales_desde_env(replace(cfg, alertas_grupo_a={"activo": True}))
    assert "telegram-A" not in _nombres(canales)
    assert "TELEGRAM_BOT_TOKEN_A" in caplog.text


def test_canales_correo_completo(cfg, monkeypatch):
    for nombre, valor in {"SMTP_HOST": "smtp.prueba.invalid", "SMTP_PORT": "2525", "SMTP_USER": "bot@prueba.invalid",
                          "SMTP_PASS": CLAVE_SMTP_PRUEBA, "SMTP_TO": "jaume@prueba.invalid"}.items():
        monkeypatch.setenv(nombre, valor)
    canales = canales_desde_env(cfg)
    assert _nombres(canales) == ["correo", "sms-nulo"]
    assert canales[0].niveles == NIVELES_CORREO
    assert canales[1].niveles == NIVELES_SMS


@pytest.mark.parametrize("variables", [
    pytest.param({"SMTP_HOST": "smtp.prueba.invalid"}, id="R-M-02-smtp-incompleto"),
    pytest.param({"SMTP_HOST": "h.invalid", "SMTP_USER": "u", "SMTP_PASS": "p" * 8, "SMTP_TO": "t", "SMTP_PORT": "abc"},
                 id="R-M-02-smtp-puerto-invalido"),
    pytest.param({"SMTP_HOST": "h.invalid", "SMTP_USER": "u", "SMTP_PASS": "p" * 8, "SMTP_TO": "t", "SMTP_PORT": "70000"},
                 id="R-M-02-smtp-puerto-fuera-de-rango"),
])
def test_canales_correo_mal_configurado_no_crea_canal(cfg, monkeypatch, caplog, variables):
    caplog.set_level(logging.WARNING, logger=LOGGER_AVISOS)
    for nombre, valor in variables.items():
        monkeypatch.setenv(nombre, valor)
    assert "correo" not in _nombres(canales_desde_env(cfg))
    assert "SMTP" in caplog.text


def test_canales_sms_proveedor_desconocido_usa_el_nulo(cfg, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_AVISOS)
    monkeypatch.setenv("SMS_PROVEEDOR", "twilio")
    assert _nombres(canales_desde_env(cfg)) == ["sms-nulo"]
    assert "twilio" in caplog.text


def test_canales_cumplen_el_protocolo(cfg, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_B", TOKEN_PRUEBA)
    monkeypatch.setenv("TELEGRAM_CHAT_ID_B", CHAT_PRUEBA)
    for canal in canales_desde_env(cfg):
        assert isinstance(canal, Canal)


# ── CanalTelegram contra un servidor HTTP local (R-M-02, R-Q-01) ────────
class ServidorTelegramFalso:
    """`http.server` local en hilo: graba cada POST y contesta lo que se le diga."""

    def __init__(self) -> None:
        self.peticiones: list[dict] = []
        self.estado = 200
        self.respuesta: bytes = b'{"ok": true, "result": {}}'
        self.retraso_s = 0.0
        self.secuencia: list[tuple[int, bytes]] = []    # (estado, respuesta) por petición; vacía → estado/respuesta
        servidor = self

        class Manejador(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — nombre fijado por http.server
                largo = int(self.headers.get("Content-Length", "0"))
                cuerpo = self.rfile.read(largo)
                servidor.peticiones.append({"ruta": self.path, "tipo": self.headers.get("Content-Type"),
                                            "json": json.loads(cuerpo.decode("utf-8"))})
                if servidor.retraso_s:
                    time.sleep(servidor.retraso_s)
                estado, respuesta = (servidor.secuencia.pop(0) if servidor.secuencia
                                     else (servidor.estado, servidor.respuesta))
                self.send_response(estado)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(respuesta)))
                self.end_headers()
                self.wfile.write(respuesta)

            def log_message(self, *args) -> None:   # el log de http.server llevaría la ruta con el token
                return

        self._http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self._http.daemon_threads = True
        self.api = f"http://127.0.0.1:{self._http.server_address[1]}"
        self._hilo = threading.Thread(target=self._http.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._hilo.start()

    def cerrar(self) -> None:
        self._http.shutdown()
        self._http.server_close()
        self._hilo.join(5.0)


@pytest.fixture
def sin_proxy(monkeypatch) -> None:
    """Que urllib no mande el 127.0.0.1 a un proxy del sistema."""
    for nombre in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")


@pytest.fixture
def servidor_tg(sin_proxy) -> Iterator[ServidorTelegramFalso]:
    servidor = ServidorTelegramFalso()
    try:
        yield servidor
    finally:
        servidor.cerrar()


def _canal_tg(api: str, timeout_s: float = 5.0) -> CanalTelegram:
    return CanalTelegram(TOKEN_PRUEBA, CHAT_PRUEBA, Grupo.B, NIVELES_TODOS, timeout_s=timeout_s, api=api)


def test_telegram_envia_el_json_esperado_y_no_loguea_el_token(servidor_tg, caplog):
    caplog.set_level(logging.DEBUG)
    canal = _canal_tg(servidor_tg.api)
    texto = "[SOMBRA] ✅ <b>FILL</b> ABC"
    assert canal.enviar(texto) is True
    assert canal.enviados == 1 and canal.fallos == 0
    (peticion,) = servidor_tg.peticiones
    assert peticion["ruta"] == f"/bot{TOKEN_PRUEBA}/sendMessage"
    assert peticion["tipo"].startswith("application/json")
    assert peticion["json"] == {"chat_id": CHAT_PRUEBA, "text": texto, "parse_mode": "HTML",
                                "disable_web_page_preview": True}
    assert TOKEN_PRUEBA not in caplog.text


@pytest.mark.parametrize(("estado", "respuesta"), [
    pytest.param(400, b'{"ok": false, "description": "Bad Request: chat not found"}', id="R-J-08-http-400"),
    pytest.param(500, b"error interno", id="R-J-08-http-500"),
    pytest.param(200, b'{"ok": false}', id="R-J-08-200-ok-false"),
    pytest.param(200, b"no es json", id="R-J-08-200-cuerpo-roto"),
])
def test_telegram_rechazos_devuelven_false_sin_token_en_el_log(servidor_tg, caplog, estado, respuesta):
    caplog.set_level(logging.DEBUG)
    servidor_tg.estado = estado
    # Un servidor que devolviera el token (p. ej. en un eco de la URL) no lo mete en el log (R-Q-01).
    servidor_tg.respuesta = respuesta + f" /bot{TOKEN_PRUEBA}/sendMessage".encode()
    canal = _canal_tg(servidor_tg.api)
    assert canal.enviar("hola") is False
    assert canal.fallos == 1
    assert TOKEN_PRUEBA not in caplog.text
    assert "bot123456789:" not in caplog.text
    assert caplog.records, "el fallo debe quedar en el log"


def test_telegram_puerto_cerrado_devuelve_false_y_no_lanza(sin_proxy, caplog):
    caplog.set_level(logging.DEBUG)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    canal = _canal_tg(f"http://127.0.0.1:{puerto}", timeout_s=2.0)
    assert canal.enviar("hola") is False
    assert TOKEN_PRUEBA not in caplog.text


def test_telegram_timeout_devuelve_false(servidor_tg, caplog):
    caplog.set_level(logging.DEBUG)
    servidor_tg.retraso_s = 1.0
    canal = _canal_tg(servidor_tg.api, timeout_s=0.2)
    t0 = time.monotonic()
    assert canal.enviar("hola") is False
    assert time.monotonic() - t0 < 1.0
    assert TOKEN_PRUEBA not in caplog.text


def test_telegram_texto_largo_se_recorta_sin_html(servidor_tg):
    canal = _canal_tg(servidor_tg.api)
    texto = "<b>" + "🔴" * 3000 + "</b>"      # 6.000 unidades UTF-16 aunque solo 3.007 caracteres
    assert canal.enviar(texto) is True
    cuerpo = servidor_tg.peticiones[0]["json"]
    assert "parse_mode" not in cuerpo
    assert "<b>" not in cuerpo["text"]
    assert unidades_utf16(cuerpo["text"]) <= 4096
    assert cuerpo["text"].endswith("…")


_ERROR_ENTIDADES = (b'{"ok": false, "error_code": 400, "description": '
                    b'"Bad Request: can\'t parse entities: Unsupported start tag \\"x\\" at byte offset 20"}')


def test_D2_08_telegram_400_entidades_reenvia_una_vez_sin_parse_mode(servidor_tg, caplog):
    """D2-08: un «<» del bróker sin escapar → 400 «can't parse entities» → UN reenvío sin parse_mode: el aviso llega."""
    caplog.set_level(logging.DEBUG)
    servidor_tg.secuencia = [(400, _ERROR_ENTIDADES)]
    canal = _canal_tg(servidor_tg.api)
    texto = "[REAL] ⛔ <b>RECHAZO</b> ABC · DAS dice: «Qty <x> MaxShare & y» · 1 &amp; 2"
    assert canal.enviar(texto) is True
    assert canal.enviados == 1 and canal.fallos == 0
    primero, segundo = (p["json"] for p in servidor_tg.peticiones)
    assert primero["parse_mode"] == "HTML" and primero["text"] == texto
    assert "parse_mode" not in segundo
    assert segundo["text"] == "[REAL] ⛔ RECHAZO ABC · DAS dice: «Qty <x> MaxShare & y» · 1 & 2", \
        "sin las etiquetas del bot, con el texto del bróker ENTERO"
    assert "sin formato" in caplog.text and TOKEN_PRUEBA not in caplog.text


def test_D2_08_telegram_reenvio_sin_formato_que_falla_cuenta_un_fallo(servidor_tg):
    """D2-08: el reenvío es UNO solo; si también falla, enviar devuelve False (la cola reintenta como siempre)."""
    servidor_tg.secuencia = [(400, _ERROR_ENTIDADES), (500, b"error interno")]
    canal = _canal_tg(servidor_tg.api)
    assert canal.enviar("<b>x</b> <y>") is False
    assert len(servidor_tg.peticiones) == 2 and canal.fallos == 1 and canal.enviados == 0


def test_D2_08_otro_400_no_se_reenvia(servidor_tg):
    """D2-08: un 400 que NO es de entidades (chat not found) no provoca reenvío."""
    servidor_tg.secuencia = [(400, b'{"ok": false, "description": "Bad Request: chat not found"}')]
    canal = _canal_tg(servidor_tg.api)
    assert canal.enviar("<b>hola</b>") is False
    assert len(servidor_tg.peticiones) == 1


def test_D2_08_escapar_es_html_escape_sin_comillas():
    """D2-08: `escapar` es el helper público (= html.escape(quote=False)); `escapar_html` da lo mismo."""
    crudo = "<b>x & y</b> \"comillas\" 'simples' Qty > MaxShare"
    assert avisos.escapar(crudo) == "&lt;b&gt;x &amp; y&lt;/b&gt; \"comillas\" 'simples' Qty &gt; MaxShare"
    assert avisos.escapar_html(crudo) == avisos.escapar(crudo)
    assert avisos.escapar(1234) == "1234"


def test_D2_08_texto_plano_telegram_solo_quita_etiquetas_de_formato():
    """D2-08: el reenvío sin formato quita <b>/<i>/<a …> y deshace entidades, pero conserva «< 5 y 7 >» del bróker."""
    texto = '<b>ABC</b> <i>x</i> <a href="https://x">enlace</a> · DAS: «qty < 5 y 7 > 3» &lt;b&gt;'
    assert avisos.texto_plano_telegram(texto) == "ABC x enlace · DAS: «qty < 5 y 7 > 3» <b>"


@pytest.mark.parametrize(("token", "chat"), [
    pytest.param("", CHAT_PRUEBA, id="R-Q-01-sin-token"),
    pytest.param(TOKEN_PRUEBA, "  ", id="R-Q-01-sin-chat"),
])
def test_telegram_exige_token_y_chat(token, chat):
    with pytest.raises(ValueError):
        CanalTelegram(token, chat, Grupo.B, NIVELES_TODOS)


@pytest.mark.parametrize(("texto", "maximo"), [
    pytest.param("corto", 10, id="cabe"),
    pytest.param("a" * 50, 10, id="ascii"),
    pytest.param("😀" * 50, 11, id="emojis-impar"),
    pytest.param("a😀" * 50, 10, id="mezcla"),
])
def test_recortar_telegram_respeta_unidades(texto, maximo):
    recortado = recortar_telegram(texto, maximo)
    assert unidades_utf16(recortado) <= maximo
    if unidades_utf16(texto) <= maximo:
        assert recortado == texto
    else:
        assert recortado.endswith("…")


# ── CanalCorreo (smtplib falso) y CanalSMS ──────────────────────────────
class SMTPFalso:
    llamadas: list = []
    fallo_en: str | None = None

    def __init__(self, host, puerto, timeout=None) -> None:
        SMTPFalso.llamadas.append(("conectar", host, puerto, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        SMTPFalso.llamadas.append(("cerrar",))
        return False

    def _paso(self, nombre, *args):
        SMTPFalso.llamadas.append((nombre, *args))
        if SMTPFalso.fallo_en == nombre:
            if nombre == "login":
                raise smtplib.SMTPAuthenticationError(535, f"credenciales malas {CLAVE_SMTP_PRUEBA}".encode())
            raise smtplib.SMTPException(f"fallo en {nombre}")

    def ehlo(self):
        self._paso("ehlo")

    def starttls(self, context=None):
        self._paso("starttls")

    def login(self, usuario, clave):
        self._paso("login", usuario, clave)

    def send_message(self, mensaje):
        self._paso("send_message", mensaje)


@pytest.fixture
def smtp_falso(monkeypatch) -> Iterator[type[SMTPFalso]]:
    SMTPFalso.llamadas = []
    SMTPFalso.fallo_en = None
    monkeypatch.setattr(avisos.smtplib, "SMTP", SMTPFalso)
    yield SMTPFalso


def _canal_correo() -> CanalCorreo:
    return CanalCorreo("smtp.prueba.invalid", 587, "bot@prueba.invalid", CLAVE_SMTP_PRUEBA, "jaume@prueba.invalid")


def test_correo_starttls_login_y_texto_plano_R_M_02(smtp_falso):
    canal = _canal_correo()
    assert canal.niveles == NIVELES_CORREO and canal.grupos == frozenset({Grupo.B})
    assert canal.enviar("[REAL] ⚠️ <b>DAS caído</b>\nsegunda línea &amp; más") is True
    pasos = [llamada[0] for llamada in smtp_falso.llamadas]
    assert pasos == ["conectar", "ehlo", "starttls", "ehlo", "login", "send_message", "cerrar"]
    mensaje = smtp_falso.llamadas[5][1]
    assert mensaje["Subject"] == "[bot DAS] [REAL] ⚠️ DAS caído"
    assert mensaje["To"] == "jaume@prueba.invalid"
    cuerpo = mensaje.get_content()
    assert "<b>" not in cuerpo and "segunda línea & más" in cuerpo


@pytest.mark.parametrize(("fallo_en", "login_llamado"), [
    pytest.param("starttls", False, id="R-Q-01-sin-tls-no-manda-la-clave"),
    pytest.param("login", True, id="R-J-08-clave-rechazada"),
    pytest.param("send_message", True, id="R-J-08-envio-fallido"),
])
def test_correo_fallos_devuelven_false_sin_clave_en_el_log(smtp_falso, caplog, fallo_en, login_llamado):
    caplog.set_level(logging.DEBUG)
    smtp_falso.fallo_en = fallo_en
    canal = _canal_correo()
    assert canal.enviar("aviso") is False
    assert canal.fallos == 1
    assert any(llamada[0] == "login" for llamada in smtp_falso.llamadas) is login_llamado
    assert CLAVE_SMTP_PRUEBA not in caplog.text


@pytest.mark.parametrize("puerto", [0, 70000, "587"])
def test_correo_valida_puerto(puerto):
    with pytest.raises(ValueError):
        CanalCorreo("h.invalid", puerto, "u", "clave123", "t")


def test_sms_nulo_loguea_y_devuelve_true_R_M_02(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_AVISOS)
    proveedor = ProveedorSMSNulo()
    canal = CanalSMS(proveedor)
    assert canal.niveles == NIVELES_SMS and canal.nombre == "sms-nulo"
    assert canal.enviar("<b>MÁXIMO</b> " + "x" * 1000) is True
    assert proveedor.enviados == 1
    assert "<b>" not in proveedor.ultimo and len(proveedor.ultimo) == avisos.SMS_MAX_CARACTERES
    assert "SMS nulo" in caplog.text


class ProveedorQueLanza:
    nombre = "roto"

    def enviar(self, texto: str) -> bool:
        raise ConnectionError("sin red")


class ProveedorQueFalla:
    nombre = "falla"

    def enviar(self, texto: str) -> bool:
        return False


@pytest.mark.parametrize("proveedor", [
    pytest.param(ProveedorQueLanza(), id="R-J-08-proveedor-lanza"),
    pytest.param(ProveedorQueFalla(), id="R-J-08-proveedor-false"),
])
def test_sms_proveedor_fallido_no_lanza(proveedor):
    canal = CanalSMS(proveedor)
    assert canal.enviar("x") is False
    assert canal.fallos == 1


# ── FiltroSecretos (R-Q-01, corrección 8, riesgo 20) ────────────────────
def test_filtro_borra_el_valor_literal_en_msg(log_filtrado):
    registro, handler = log_filtrado
    registro.warning(f"LOGIN bot {CLAVE_DAS_PRUEBA} cuenta 0 y token {TOKEN_PRUEBA}")
    (linea,) = handler.lineas
    assert CLAVE_DAS_PRUEBA not in linea and TOKEN_PRUEBA not in linea
    assert linea == f"LOGIN bot {MASCARA} cuenta 0 y token {MASCARA}"


def test_filtro_borra_en_args_tupla_sin_romper_el_formateo(log_filtrado):
    registro, handler = log_filtrado
    registro.warning("n=%d clave=%s token=%r x=%.2f", 5, CLAVE_DAS_PRUEBA, TOKEN_PRUEBA, 1.5)
    assert handler.lineas == [f"n=5 clave={MASCARA} token='{MASCARA}' x=1.50"]


def test_filtro_borra_en_args_dict(log_filtrado):
    registro, handler = log_filtrado
    registro.warning("clave=%(c)s n=%(n)d", {"c": CLAVE_DAS_PRUEBA, "n": 7})
    assert handler.lineas == [f"clave={MASCARA} n=7"]


def test_filtro_borra_en_args_anidados_y_objetos(log_filtrado):
    registro, handler = log_filtrado

    class ConSecreto:
        def __str__(self) -> str:
            return f"objeto con {CLAVE_DAS_PRUEBA}"

    registro.warning("lista=%s objeto=%s", ["a", CLAVE_DAS_PRUEBA], ConSecreto())
    (linea,) = handler.lineas
    assert CLAVE_DAS_PRUEBA not in linea
    assert MASCARA in linea


def test_filtro_borra_la_forma_url_de_un_token_desconocido():
    filtro = FiltroSecretos([])
    url = "https://api.telegram.org/bot111222333:XYZ_abc-9/sendMessage"
    assert filtro.limpiar(url) == f"https://api.telegram.org/{MASCARA}/sendMessage"


def test_filtro_borra_la_traza_de_una_excepcion(log_filtrado):
    registro, handler = log_filtrado
    try:
        raise ValueError(f"login rechazado para {CLAVE_DAS_PRUEBA}")
    except ValueError:
        registro.exception("fallo")
    (linea,) = handler.lineas
    assert "ValueError" in linea and CLAVE_DAS_PRUEBA not in linea


def test_filtro_limpia_exc_text_ya_formateado_por_otro_handler():
    filtro = FiltroSecretos([CLAVE_DAS_PRUEBA])
    registro = logging.LogRecord("x", logging.ERROR, __file__, 1, "fallo", None, None)
    registro.exc_text = f"Traceback ... {CLAVE_DAS_PRUEBA}"
    filtro.filter(registro)
    assert CLAVE_DAS_PRUEBA not in registro.exc_text


@pytest.mark.parametrize(("secretos", "esperados"), [
    pytest.param(["abc", "", None, "  "], (), id="R-Q-01-cortos-y-vacios-ignorados"),
    pytest.param(["abcde", "abcd"], ("abcde", "abcd"), id="SEG-04-4-y-5-caracteres-se-tapan"),
    pytest.param(["abcdef", "abcdefghij"], ("abcdefghij", "abcdef"), id="R-Q-01-el-mas-largo-primero"),
    pytest.param([" abcdef "], ("abcdef",), id="R-Q-01-sin-espacios"),
])
def test_filtro_solo_secretos_de_longitud_minima(secretos, esperados):
    assert FiltroSecretos(secretos).secretos == esperados


def test_SEG_04_clave_de_das_de_5_caracteres_se_tapa():
    """SEG-04: una DAS_CLAVE corta (5 caracteres) ya no sale en claro en el log, el diario ni /log."""
    filtro = FiltroSecretos(["abc12"])
    assert filtro.limpiar("clave abc12 aqui") == f"clave {MASCARA} aqui"
    assert filtro.cortos == 0


def test_SEG_04_secretos_demasiado_cortos_se_cuentan_y_se_avisan_sin_su_valor(dir_bot, reloj, caplog):
    """SEG-04: un secreto de < 4 caracteres no se puede tapar: se cuenta y instalar_logging avisa (sin el valor)."""
    filtro = FiltroSecretos(["xq9", "", None, CLAVE_DAS_PRUEBA])
    assert filtro.cortos == 1 and filtro.secretos == (CLAVE_DAS_PRUEBA,)
    caplog.set_level(logging.WARNING, logger=LOGGER_AVISOS)
    try:
        instalar_logging("ejecutor", dir_bot / "logs", ["xq9"], consola=False, reloj=reloj)
    finally:
        desinstalar_logging()
    avisos_cortos = [r.getMessage() for r in caplog.records if "NO se pueden tapar" in r.getMessage()]
    assert len(avisos_cortos) == 1 and "xq9" not in avisos_cortos[0]


@pytest.mark.parametrize(("formato", "valor", "esperado"), [
    pytest.param("cuenta %d", 987654321, f"cuenta {MASCARA}", id="C-03-entero-%d"),
    pytest.param("importe %.2f", 987654321.5, f"importe {MASCARA}.50", id="C-03-float-%.2f"),
    pytest.param("id %d y n=%d", 19876543210, f"id 1{MASCARA}0 y n=5", id="C-03-cifras-dentro-de-un-numero"),
])
def test_C_03_secreto_numerico_en_un_arg_no_str_no_rompe_el_formateo(formato, valor, esperado):
    """C-03: un secreto de solo cifras en un arg %d/%.2f se tapa y la línea NO se pierde («--- Logging error ---»)."""
    registro = logging.getLogger("prueba.bot_das.filtro_numerico")
    handler = ListaHandler()
    handler.addFilter(FiltroSecretos(["987654321"]))
    registro.addHandler(handler)
    registro.setLevel(logging.DEBUG)
    registro.propagate = False
    try:
        args = (valor, 5) if formato.count("%") == 2 else (valor,)
        registro.warning(formato, *args)
    finally:
        registro.removeHandler(handler)
        registro.propagate = True
    assert handler.lineas == [esperado]
    assert "987654321" not in handler.lineas[0]


def test_C_03_arg_numerico_sin_secreto_conserva_el_formateo_perezoso(log_filtrado):
    """C-03: sin secreto en los números, `args` sigue intacto (el % lo hace el Formatter, como antes)."""
    registro, handler = log_filtrado
    registro.warning("n=%d x=%.3f", 42, 0.5)
    assert handler.lineas == ["n=42 x=0.500"]


def test_filtro_el_mas_largo_se_tapa_entero():
    filtro = FiltroSecretos(["abcdef", "abcdefghij"])
    assert filtro.limpiar("x abcdefghij y abcdef") == f"x {MASCARA} y {MASCARA}"


def test_secretos_desde_env_lee_en_la_llamada(monkeypatch):
    assert secretos_desde_env() == []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_B", TOKEN_PRUEBA)
    monkeypatch.setenv("DAS_CLAVE", CLAVE_DAS_PRUEBA)
    monkeypatch.setenv("SMTP_PASS", CLAVE_SMTP_PRUEBA)
    monkeypatch.setenv("BOT_DAS_AUTHKEY", "")
    assert sorted(secretos_desde_env()) == sorted([TOKEN_PRUEBA, CLAVE_DAS_PRUEBA, CLAVE_SMTP_PRUEBA])


# ── instalar_logging ────────────────────────────────────────────────────
@pytest.fixture
def logging_instalado(dir_bot, reloj) -> Iterator[Path]:
    directorio = dir_bot / "logs"
    try:
        instalar_logging("ejecutor", directorio, [TOKEN_PRUEBA, CLAVE_DAS_PRUEBA], consola=True, reloj=reloj)
        yield directorio
    finally:
        desinstalar_logging()


def _propios() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if hasattr(h, "bot_das_proceso")]


def test_instalar_logging_fichero_por_proceso_y_dia_sin_secretos_riesgo_20(logging_instalado, reloj):
    logging.getLogger("btt.bot_das.prueba").warning("clave=%s url=/bot%s/getUpdates", CLAVE_DAS_PRUEBA, TOKEN_PRUEBA)
    for handler in _propios():
        handler.flush()
    ruta = ruta_log(logging_instalado, "ejecutor", reloj.hoy())
    assert ruta.name == "bot_das_ejecutor_2026-09-25.log"
    contenido = ruta.read_text(encoding="utf-8")
    assert "clave=*****" in contenido
    assert CLAVE_DAS_PRUEBA not in contenido and TOKEN_PRUEBA not in contenido
    assert any(CLAVE_DAS_PRUEBA not in linea and "clave=*****" in linea for linea in ultimas_lineas_log(5))
    assert all(any(isinstance(f, FiltroSecretos) for f in h.filters) for h in _propios())
    assert {type(h).__name__ for h in _propios()} == {"HandlerFicheroDiario", "MemoriaLog", "StreamHandler"}
    for ruidoso in ("httpx", "urllib3"):
        assert logging.getLogger(ruidoso).level == logging.WARNING


def test_instalar_logging_es_idempotente(logging_instalado, reloj):
    instalar_logging("ejecutor", logging_instalado, [], consola=False, reloj=reloj)
    assert len(_propios()) == 2


def test_desinstalar_restaura_handlers_y_nivel(dir_bot, reloj):
    raiz = logging.getLogger()
    nivel_antes, ajenos_antes = raiz.level, [h for h in raiz.handlers if not hasattr(h, "bot_das_proceso")]
    try:
        instalar_logging("vigilante", dir_bot / "logs", [], nivel=logging.DEBUG, consola=False, reloj=reloj)
        assert raiz.level == logging.DEBUG
    finally:
        desinstalar_logging()
    assert raiz.level == nivel_antes
    assert _propios() == []
    assert [h for h in raiz.handlers if not hasattr(h, "bot_das_proceso")] == ajenos_antes
    assert ultimas_lineas_log() == []


def test_handler_fichero_cambia_de_fichero_al_cambiar_el_dia(tmp_path, reloj):
    handler = HandlerFicheroDiario(tmp_path, "supervisor", reloj)
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.emit(logging.LogRecord("x", logging.INFO, __file__, 1, "viernes", None, None))
        reloj.avanzar(24 * 3600)
        handler.emit(logging.LogRecord("x", logging.INFO, __file__, 1, "sábado", None, None))
    finally:
        handler.close()
    assert (tmp_path / "bot_das_supervisor_2026-09-25.log").read_text(encoding="utf-8").strip() == "viernes"
    assert (tmp_path / "bot_das_supervisor_2026-09-26.log").read_text(encoding="utf-8").strip() == "sábado"


# ── textos (R-O-03, R-B-07, R-M-05) ─────────────────────────────────────
@pytest.mark.parametrize(("fase", "prefijo"), [
    pytest.param(Fase.SOMBRA, "[SOMBRA]", id="R-O-03-sombra"),
    pytest.param(Fase.CANARIO, "[CANARIO]", id="R-O-03-canario"),
    pytest.param(Fase.REAL, "[REAL]", id="R-O-03-real"),
])
def test_prefijo_de_fase(fase, prefijo):
    assert prefijo_fase(fase) == prefijo
    assert prefijo_fase(fase.value) == prefijo
    assert con_prefijo_fase("hola", fase) == f"{prefijo} hola"
    assert con_prefijo_fase(f"{prefijo} hola", fase) == f"{prefijo} hola"


def _lote() -> Lote:
    return Lote(id="ABC|prueba-1|2026-09-25 09:31:00|entrada", strategy_id="prueba-1", estrategia="PM (A) prueba",
                ticker="ABC", direccion="Short", pedidas=1000, llenas=600, precio_medio=Decimal("2.35"),
                nivel_stop=Decimal("2.6"), estado=EstadoLote.ABRIENDO)


def _fill(ticker="ABC", simulado=False, precio=Decimal("2.35")) -> Fill:
    return Fill(id_trade=77, token=100_268_00001, id_orden=5, ticker=ticker, lado="SS", qty=600, precio=precio,
                ruta="SAGEREB", hora="09:31:02", liq=None, ecn_fee=None, simulado=simulado)


@pytest.mark.parametrize("fase", list(Fase), ids=[f"R-O-03-{f.value}" for f in Fase])
def test_texto_fill_lleva_la_fase_y_los_datos(cfg, fase):
    texto = texto_fill(_lote(), _fill(), cfg, fase)
    assert texto.startswith(prefijo_fase(fase))
    assert "<b>ABC</b>" in texto and "CORTO" in texto
    assert "<b>600</b> @ <b>2,35</b>" in texto
    assert "Lote: 600/1.000" in texto and "stop 2,60" in texto
    assert "PM (A) prueba" in texto and "SAGEREB" in texto and "09:31:02" in texto
    assert "SIMULADO" not in texto


def test_texto_fill_simulado_escapa_html_y_precio_bajo_1(cfg):
    texto = texto_fill(_lote(), _fill(ticker="A<B", simulado=True, precio=Decimal("0.1234")), cfg, Fase.SOMBRA)
    assert "A&lt;B" in texto and "A<B" not in texto
    assert "SIMULADO" in texto
    assert "@ <b>0,1234</b>" in texto


def test_texto_fill_con_estrategia_que_no_esta_en_la_config(cfg):
    lote = replace(_lote(), strategy_id="retirada", estrategia="Vieja")
    assert "Vieja" in texto_fill(lote, _fill(), cfg, Fase.REAL)


@pytest.mark.parametrize(("precio", "texto"), [
    pytest.param(None, "—", id="sin-precio"),
    pytest.param(Decimal("1234.5"), "1.234,50", id="miles"),
    pytest.param(Decimal("0.0512"), "0,0512", id="bajo-1"),
    pytest.param(Decimal("1"), "1,00", id="uno"),
])
def test_formatear_precio(precio, texto):
    assert formatear_precio(precio) == texto


def _orden(**kw) -> Orden:
    base = dict(token=100_268_00002, ticker="ABC", lado=Lado.CORTO, tipo=TipoOrden.LIMITE, qty=1000,
                precio=Decimal("2.34"), stop=None, ruta="SAGEREB", proposito=Proposito.ENTRADA_AGREGAR,
                lote_id="L1", nivel=None, origen=Origen.EJECUTOR, id_das=4321, intentos=1)
    base.update(kw)
    return Orden(**base)


def _posicion() -> PosicionTicker:
    return PosicionTicker(ticker="ABC", lotes={"L1": _lote()}, neta_fills=-600, estado=EstadoTicker.PAUSADO,
                          motivo_estado="rechazo de DAS")


def test_texto_rechazo_lleva_el_literal_de_das_la_orden_y_el_ticker_R_B_07():
    notas = "Short Locate is not available <ABC>"
    texto = texto_rechazo(_orden(), notas, _posicion())
    assert "RECHAZO" in texto and "<b>ABC</b>" in texto and "entrada_agregar" in texto
    assert "«Short Locate is not available &lt;ABC&gt;»" in texto
    assert "CORTO 1.000 LMT @ 2,34" in texto and "ruta SAGEREB" in texto
    assert "token 10026800002" in texto and "id 4321" in texto and "intento 1" in texto
    assert "Ticker: pausado (rechazo de DAS)" in texto and "neta -600" in texto and "lotes 1" in texto


@pytest.mark.parametrize(("orden", "fragmento"), [
    pytest.param(_orden(tipo=TipoOrden.MERCADO, precio=None), "MKT a mercado", id="R-B-07-mercado"),
    pytest.param(_orden(tipo=TipoOrden.STOP_LIMITE_PP, lado=Lado.COMPRA, stop=Decimal("2.6"), precio=Decimal("2.68"),
                        proposito=Proposito.STOP_PRINCIPAL), "stop 2,60 · límite 2,68", id="R-B-07-stop-limite"),
])
def test_texto_rechazo_por_tipo_de_orden(orden, fragmento):
    assert fragmento in texto_rechazo(orden, "", _posicion())
    assert "«(sin texto)»" in texto_rechazo(orden, "   ", _posicion())


def test_texto_rechazo_con_fase_lleva_prefijo_R_O_03():
    assert texto_rechazo(_orden(), "x", _posicion(), Fase.CANARIO).startswith("[CANARIO] ")
    assert texto_rechazo(_orden(), "x", _posicion()).startswith("⛔")


def test_texto_grupo_a_reutiliza_el_formato_de_hoy_R_M_05():
    from app.services.bot_alerts_engine import Evento
    from app.services.bot_alerts_telegram import formatear_grupo

    comun = dict(tipo="entrada", ticker="ABC", strategy_id="prueba-1", estrategia="PM (A) prueba",
                 momento="2026-09-25 09:31:00", precio=2.35, direccion="Short", stop=2.6)
    principal = Evento(**comun, acciones=1000.0, riesgo_usd=250.0)
    otra = Evento(**comun, acciones=400.0, riesgo_usd=100.0, cuenta="socio")
    distinta = Evento(**{**comun, "ticker": "XYZ"}, acciones=10.0, riesgo_usd=5.0)
    textos = texto_grupo_a([principal, otra, distinta])
    assert len(textos) == 2                     # misma señal en dos cuentas = UN mensaje
    assert textos[0] == formatear_grupo([principal, otra])
    assert textos[1] == formatear_grupo([distinta])
    assert texto_grupo_a([]) == []


# ── importar no ejecuta nada; sin httpx propio (riesgo 20) ──────────────
def test_importar_avisos_no_arranca_hilos_ni_carga_pandas():
    codigo = ("import sys, threading; sys.path.insert(0, '.'); import app.bot_das.avisos; "
              "print(threading.active_count(), 'pandas' in sys.modules)")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=BACKEND, capture_output=True, text=True, timeout=60)
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.split() == ["1", "False"]


def test_avisos_no_usa_httpx_riesgo_20():
    fuente = Path(avisos.__file__).read_text(encoding="utf-8")
    assert "import httpx" not in fuente and "httpx." not in fuente


def test_SEG_05_importar_avisos_no_carga_httpx():
    """SEG-05: importar avisos (y por él ejecutor, vigilante, supervisor, comprobar_das) NO mete httpx en el proceso."""
    codigo = ("import sys; sys.path.insert(0, '.'); import app.bot_das.avisos; "
              "print('httpx' in sys.modules, 'app.services.bot_alerts_telegram' in sys.modules)")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=BACKEND, capture_output=True, text=True, timeout=60)
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.split() == ["False", "False"]


def test_C_04_texto_rechazo_no_esta_en_el_camino_de_ordenes():
    """C-04: el aviso de rechazo que sale a Telegram es el de reglas.rechazos (un solo contrato vivo).

    `avisos.texto_rechazo` queda como formato de consulta: ningún módulo del
    paquete lo usa para avisar (si alguien lo engancha, que sea a propósito
    y cambiando este test y el contrato de rechazos a la vez).
    """
    paquete = Path(avisos.__file__).resolve().parent
    usos = [p.relative_to(paquete).as_posix() for p in paquete.rglob("*.py")
            if p.name != "avisos.py" and "texto_rechazo" in p.read_text(encoding="utf-8")]
    assert usos == []
    fuente_rechazos = (paquete / "reglas" / "rechazos.py").read_text(encoding="utf-8")
    assert "def _texto_aviso" in fuente_rechazos and "html.escape" in fuente_rechazos
