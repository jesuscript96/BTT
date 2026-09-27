"""Tests del proceso vigilante (lote G2): plan B de los stops con DAS de verdad por socket, neteo con el ejecutor y ping.

QUÉ PRUEBA. `app.bot_das.vigilante` en tres alturas:
  1. Piezas: `ColaVigilante` (cola de los hilos de borde), `PingExterno`
     (R-J-05: cada 60 s, sin bloquear, sin URL no pinga, fallos seguidos), el
     seguidor incremental del diario y la ventana por horario.
  2. `VigilanteDAS` contra el `SimuladorDAS` en 127.0.0.1:0 con su conexión
     WATCH real (`LOGIN … 1`) y una segunda conexión NORMAL de acción: posición
     sin stop con el ejecutor callado ⇒ par principal + emergencia repuesto en
     < 2 s (R-C-07 plan B); luego un ejecutor REAL arranca y lo adopta sin
     mandar ni una orden (F13); ejecutor vivo ⇒ espera el plazo de
     descubierta; sin conexión de acción ⇒ petición al supervisor
     (corrección 16); sombra sin un solo mutante (R-O-03); rechazos con
     separación y tope (R-C-03, riesgo 11); posición sin lote (R-C-10 4);
     locates repetidos (R-H-02); orden «parar» del supervisor (R-L-01); doble
     instancia (R-J-04 c); latido retenido (injerto §8.11); caída y
     reconexión del watch (R-J-02); ping solo si todo va bien (R-J-05).
  3. `construir_desde_env` y `main` sin red y sin el `.env` real.

LAS TRAMPAS.
  * Ninguna credencial: usuario, clave y cuenta son textos INVENTADOS que
    solo ve el simulador local; el `.env` real no se carga nunca
    (`RUTA_DOTENV` apunta a un fichero inexistente).
  * El reloj es simulado y está PARADO (09:30 ET del 25-sep): lo que depende
    del tiempo de decisión (plan B, pendientes, separación, dedupe) solo
    avanza cuando el test mueve el reloj. Los mensajes de DAS llegan en tiempo
    real: el test bombea `paso(forzar=True)` hasta que se cumple la condición
    (con plazo real) o corre `correr()` en un hilo (el «< 2 s» es de reloj
    real).
  * El ejecutor de la prueba de adopción se construye con piezas reales
    (Decisor, ClienteDAS, diario) y dobles sin red para la fuente, los avisos,
    la referencia de Massive y el calendario.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from app.bot_das import VERSION, protocolo
from app.bot_das import vigilante as vg
from app.bot_das.cerrojo import CerrojoInstancia, Latido
from app.bot_das.cliente import ClienteDAS, PlanReconexion
from app.bot_das.diario import Diario, LectorDiario, nombre_fichero
from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.tipos import (
    Aviso,
    Config,
    Fase,
    Ficha,
    MsgOrderAct,
    MsgPos,
    Nivel,
    Origen,
    Proposito,
    Registro,
)
from app.bot_das.tokens import componer, descomponer

D = Decimal
INICIO = datetime(2026, 9, 25, 9, 30, tzinfo=ET)          # el del reloj de conftest (viernes)
HOY = INICIO.date()
DIA = HOY.timetuple().tm_yday
TICKER = "XYZ"
SID = "prueba-1"
NOMBRE_ESTRATEGIA = "PM (A) prueba"
LOTE_ID = f"{TICKER}|{SID}|2026-09-25 09:29:00|entrada"
CUENTA = "CUENTA_PRUEBA"                                   # la del simulador: inventada
USUARIO = "usuario_vigilante_prueba"                       # inventado
CLAVE_DAS = "clave-inventada-vigilante-5521"               # inventada: solo la ve el simulador local
PLAZO_S = 10.0                                             # plazo REAL para que llegue algo por el socket
URL_PING = "https://ping.ejemplo.invalid/ping/identificador-inventado-4471"


# ═══════════════════════════ dobles ══════════════════════════════════════
class AvisosGrabados:
    """La cola de avisos, síncrona, en memoria y segura entre hilos (el vigilante puede correr en otro hilo)."""

    def __init__(self) -> None:
        self._avisos: list[Aviso] = []
        self._cerrojo = threading.Lock()
        self.arrancado = False
        self.parado_con: Optional[float] = None
        self.vivo = True

    def poner(self, aviso: Aviso) -> None:
        with self._cerrojo:
            self._avisos.append(aviso)

    def arrancar(self) -> None:
        self.arrancado = True

    def parar(self, espera_s: float = 30.0) -> None:
        self.parado_con = espera_s

    def foto(self) -> dict:
        return {"pendientes": 0}

    @property
    def avisos(self) -> list[Aviso]:
        with self._cerrojo:
            return list(self._avisos)

    def con_clave(self, prefijo: str) -> list[Aviso]:
        return [a for a in self.avisos if a.clave is not None and a.clave.startswith(prefijo)]


class AbrirAccion:
    """`abrir_accion` de la prueba: un LOGIN normal contra el simulador (o None si «DAS no admite otra conexión»)."""

    def __init__(self, direccion: tuple[str, int], reloj: RelojSimulado, cola: vg.ColaVigilante,
                 disponible: bool = True) -> None:
        self.direccion = direccion
        self.reloj = reloj
        self.cola = cola
        self.disponible = disponible
        self.llamadas = 0
        self.clientes: list[ClienteDAS] = []

    def __call__(self) -> Optional[ClienteDAS]:
        self.llamadas += 1
        if not self.disponible:
            return None
        host, puerto = self.direccion
        cliente = ClienteDAS(host, puerto, USUARIO, CLAVE_DAS, CUENTA, False, False, self.cola.al_mensaje_accion,
                             self.cola.al_estado_accion, self.reloj)
        self.clientes.append(cliente)
        return cliente

    def cerrar(self) -> None:
        for cliente in self.clientes:
            cliente.cerrar()


class WatchSordo:
    """Un «watch» que no conecta y cuyo lector está muerto (latido retenido, injerto §8.11)."""

    def __init__(self) -> None:
        self.hilos_vivos = False
        self.conectado = False
        self.enviadas: list[str] = []

    def conectar(self) -> bool:
        return False

    def cerrar(self) -> None:
        self.conectado = False

    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> None:
        self.enviadas.append(linea)


class RespuestaFalsa:
    def __init__(self, status: int) -> None:
        self.status = status
        self.cerrada = False

    def close(self) -> None:
        self.cerrada = True


class AbrirPing:
    """`urlopen` falso: registra (url, timeout), puede tardar, fallar o devolver un estado."""

    def __init__(self, status: int = 200, falla: Optional[BaseException] = None, tarda_s: float = 0.0) -> None:
        self.status = status
        self.falla = falla
        self.tarda_s = tarda_s
        self.llamadas: list[tuple[str, float]] = []
        self._cerrojo = threading.Lock()

    def __call__(self, url: str, timeout: float) -> RespuestaFalsa:
        with self._cerrojo:
            self.llamadas.append((url, timeout))
        if self.tarda_s:
            time.sleep(self.tarda_s)
        if self.falla is not None:
            raise self.falla
        return RespuestaFalsa(self.status)


class ReferenciaFalsa:
    """`ficha`/`splits_de_hoy` de Massive en memoria (la real abre red)."""

    def ficha(self, ticker: str) -> Ficha:
        return Ficha(ticker=ticker, list_date=date(2020, 1, 1), sic_code="1234", tipo="CS",
                     market_cap=D("100000000"), nombre="Prueba SA")

    def splits_de_hoy(self, dia: date) -> set[str]:
        return set()


class CalendarioPrueba:
    """Franja por la hora ET, sin festivos ni red (el real pregunta a Massive en un hilo)."""

    def franja_de_mercado(self, ahora: datetime) -> str:
        minutos = ahora.hour * 60 + ahora.minute
        if 4 * 60 <= minutos < 9 * 60 + 30:
            return "premercado"
        if 9 * 60 + 30 <= minutos < 16 * 60:
            return "RTH"
        if 16 * 60 <= minutos < 20 * 60:
            return "postmercado"
        return "cerrado"

    def media_sesion(self, dia: date) -> Optional[str]:
        return None


class FuenteManual:
    """Una fuente de señales que no produce nada (el ejecutor de la adopción no abre posiciones)."""

    origen = "manual"

    def __init__(self) -> None:
        self.viva = False

    def arrancar(self) -> None:
        self.viva = True

    def parar(self) -> None:
        self.viva = False

    def salud(self) -> dict:
        return {"viva": self.viva, "ultimo_en": None, "origen": self.origen, "ultimo_error": None}


# ═══════════════════════════ utilidades ══════════════════════════════════
def tok(seq: int, origen: Origen = Origen.EJECUTOR) -> int:
    return componer(origen, DIA, seq)


def registros(dir_bot: Path, proceso: str = "vigilante") -> list[Registro]:
    return LectorDiario(dir_bot / "diario").leer(HOY, (proceso,))


def de_tipo(regs: list[Registro], tipo: str) -> list[Registro]:
    return [r for r in regs if r.tipo == tipo]


def neworders(lineas: list[str], ticker: Optional[str] = None) -> list[str]:
    salida = []
    for linea in lineas:
        p = linea.split()
        if p and p[0].upper() == "NEWORDER" and (ticker is None or p[3] == ticker):
            salida.append(linea)
    return salida


def escribir_latido_ejecutor(dir_bot: Path, epoch: float) -> None:
    (dir_bot / "estado" / vg.NOMBRE_LATIDO_EJECUTOR).write_text(repr(float(epoch)), encoding="ascii")


def escribir_diario_ejecutor(dir_bot: Path, reloj: RelojSimulado, nivel: str = "4.00", qty: int = 100,
                             extra: Callable[[Diario], None] = lambda d: None) -> None:
    """El diario del ejecutor tras una entrada corta de `qty` llena (lote abierto con nivel de stop), sin stops."""
    d = Diario(dir_bot / "diario", reloj, "ejecutor", VERSION, Fase.CANARIO)
    d.abrir_dia(HOY, motor_hash="sha256:" + "0" * 64, config_version=1)
    token = tok(1)
    d.anotar("senal", ticker=TICKER, senal_id=LOTE_ID, tipo="entrada", strategy_id=SID)
    d.anotar("lote", ticker=TICKER, lote_id=LOTE_ID, strategy_id=SID, estrategia=NOMBRE_ESTRATEGIA, direccion="short",
             pedidas=qty, llenas=0, precio_medio="0", nivel_stop=nivel, riesgo_usd="55", estado="abriendo",
             reentrada_n=0, entrada_idx=0)
    d.anotar("orden_intencion", ticker=TICKER, token=token, lado="SS", tipo_orden="LMT", qty=qty, precio=D("3.45"),
             stop=None, ruta="SAGEREB", post_only=True, tif="DAY+", proposito="entrada_agregar", lote_id=LOTE_ID,
             nivel=D(nivel), version=0, origen=1)
    d.anotar("orden_enviada", ticker=TICKER, token=token)
    d.anotar("fill", ticker=TICKER, id_trade=7001, token=token, id_orden=None, lado="SS", qty=qty, precio=D("3.45"),
             ruta="SAGEREB", hora="09:29:30", liq="A", ecn_fee=None)
    d.anotar("lote", ticker=TICKER, lote_id=LOTE_ID, llenas=qty, precio_medio="3.45", estado="abierto")
    extra(d)
    d.cerrar()


def stops_vivos(libro: Any, ticker: str = TICKER) -> list[dict]:
    return [o for o in libro.ordenes() if o["ticker"] == ticker and o["tipo"] == "STOPLMTP"
            and o["estado"] in ("Accepted", "Partial")]


@dataclasses.dataclass
class Montaje:
    v: vg.VigilanteDAS
    cola: vg.ColaVigilante
    avisos: AvisosGrabados
    abrir: AbrirAccion
    dir_bot: Path
    reloj: RelojSimulado
    simulador: Any
    libro: Any

    def regs(self, proceso: str = "vigilante") -> list[Registro]:
        return registros(self.dir_bot, proceso)

    def bombear(self, cond: Callable[[], bool], que: str, plazo_s: float = PLAZO_S) -> None:
        """`paso(forzar=True)` hasta que `cond()` (con plazo REAL): cada vuelta es una pasada de vigilancia."""
        limite = time.monotonic() + plazo_s
        while not cond():
            if time.monotonic() > limite:
                pytest.fail(f"plazo vencido esperando: {que}; DAS recibió {self.simulador.recibidas()[-8:]}; "
                            f"diario {[r.tipo for r in self.regs()][-12:]}")
            assert self.v.paso(0.02, forzar=True) is None

    def pasadas(self, n: int) -> None:
        for _ in range(n):
            assert self.v.paso(0.02, forzar=True) is None

    def listo(self) -> None:
        """Hasta que el volcado del watch esté entero (la primera pasada útil)."""
        self.bombear(lambda: self.v._watch_listo(), "volcado del watch")

    def recibidas(self) -> list[str]:
        return self.simulador.recibidas()


@pytest.fixture
def cfg_canario(cfg: Config) -> Config:
    return dataclasses.replace(cfg, fase=Fase.CANARIO)


@pytest.fixture
def montar(cfg_canario: Config, reloj: RelojSimulado, dir_bot: Path, libro: Any, simulador: Any,
           direccion_simulador: tuple[str, int]):
    creados: list[Montaje] = []

    def crear(*, config: Optional[Config] = None, accion: bool | Callable[[], Any] = True,
              ping: Optional[vg.PingExterno] = None, watch: Any = None, cola: Optional[vg.ColaVigilante] = None,
              dentro: Optional[Callable[[datetime], bool]] = None, plan: Optional[PlanReconexion] = None,
              arrancar: bool = True) -> Montaje:
        c = config if config is not None else cfg_canario
        cola = cola if cola is not None else vg.ColaVigilante()
        host, puerto = direccion_simulador
        if watch is None:
            watch = ClienteDAS(host, puerto, USUARIO, CLAVE_DAS, CUENTA, True, True, cola.al_mensaje, cola.al_estado,
                               reloj, al_aviso=cola.al_aviso, al_caida_hilo=cola.al_caida_hilo)
        abrir = AbrirAccion(direccion_simulador, reloj, cola, disponible=accion is True)
        avisos = AvisosGrabados()
        estado = dir_bot / "estado"
        v = vg.VigilanteDAS(c, watch, accion if callable(accion) else abrir, LectorDiario(dir_bot / "diario"),
                            Diario(dir_bot / "diario", reloj, "vigilante", VERSION, c.fase), avisos, reloj,
                            Latido(estado / vg.NOMBRE_LATIDO, reloj), CerrojoInstancia(estado / vg.NOMBRE_CERROJO),
                            estado / vg.NOMBRE_LATIDO_EJECUTOR, ping, estado / vg.NOMBRE_ORDEN_SUPERVISOR, cola=cola,
                            dentro_de_ventana=dentro if dentro is not None else (lambda ahora_et: True),
                            plan_reconexion=plan, espera_avisos_s=0.1)
        m = Montaje(v, cola, avisos, abrir, dir_bot, reloj, simulador, libro)
        creados.append(m)
        if arrancar:
            assert v.arrancar() == vg.CODIGO_OK
        return m

    yield crear
    for m in creados:
        m.v.parar()
        m.abrir.cerrar()


# ═══════════════════════════ 1. piezas ═══════════════════════════════════
def test_cola_encola_por_etiqueta_y_de_la_accion_solo_pasan_los_orderact() -> None:
    """§6.1: los hilos de borde solo encolan; de la conexión de acción solo interesa `%OrderAct` (lo demás llega por watch)."""
    cola = vg.ColaVigilante()
    pos = protocolo.parsear(f"%IPOS {TICKER} 3 100 3.45 0 0 0.00 2026/09/25-09:29:00 0.00")
    assert isinstance(pos, MsgPos)
    cola.al_mensaje(pos)
    cola.al_estado(True, "ok")
    act = protocolo.parsear(f"%OrderAct 1001 Accept B {TICKER} 100 4.12 STOP 09:30:00  {tok(1, Origen.VIGILANTE)}")
    assert isinstance(act, MsgOrderAct)
    cola.al_mensaje_accion(act)
    cola.al_mensaje_accion(pos)                                   # volcado de la conexión de acción: fuera
    cola.al_estado_accion(False, "EOF")
    cola.al_caida_hilo("das-lector", "OSError: x", True)
    cola.al_intento_watch(False)
    eventos = []
    while (e := cola.sacar(0)) is not None:
        eventos.append(e)
    assert [e[0] for e in eventos] == [vg.EVENTO_WATCH, vg.EVENTO_ESTADO_WATCH, vg.EVENTO_ACCION,
                                        vg.EVENTO_ESTADO_ACCION, vg.EVENTO_HILO, vg.EVENTO_INTENTO_WATCH]
    assert eventos[0][1] is pos and eventos[2][1] is act and cola.descartados_accion == 1
    assert cola.sacar(0.01) is None and cola.tamano() == 0
    with pytest.raises(TypeError):
        cola.al_mensaje("no es un mensaje")                       # type: ignore[arg-type]


def test_cola_avisos_de_borde_con_tope_descartan_el_mas_viejo() -> None:
    """R-J-08: la cola de avisos de borde tiene tope; se pierde el más viejo y se cuenta. Nivel fuera de 1-3 → 2."""
    cola = vg.ColaVigilante(tope_avisos=2)
    cola.al_aviso("uno")
    cola.al_aviso_nivel(3, "dos", "clave")
    cola.al_aviso_nivel(9, "tres")
    assert cola.avisos_pendientes() == [(Nivel.MAXIMO, "dos", "clave"), (Nivel.AVISO, "tres", None)]
    assert cola.avisos_perdidos == 1 and cola.avisos_pendientes() == []
    with pytest.raises(ValueError):
        vg.ColaVigilante(tope_avisos=0)


@pytest.mark.parametrize("url", ["", "   ", "ftp://ping.ejemplo.invalid/x", "no-es-una-url", "https://"],
                         ids=["R-J-05-vacia", "R-J-05-blancos", "R-J-05-ftp", "R-J-05-texto", "R-J-05-sin-host"])
def test_ping_sin_url_valida_avisa_una_vez_y_no_pinga(reloj: RelojSimulado, url: str) -> None:
    """R-J-05: sin BOT_DAS_PING_URL (o no http/https) no hay ping: aviso 2 UNA vez, nunca se llama a abrir."""
    avisos: list[tuple] = []
    abrir = AbrirPing()
    ping = vg.PingExterno(url, reloj, abrir=abrir, al_aviso=lambda n, t, c: avisos.append((n, t, c)))
    assert not ping.activo
    for i in range(3):
        ping.tocar_si_toca(1000.0 + i * 100)
    assert ping.avisar_si_falta_url() is True
    assert abrir.llamadas == [] and ping.intentos == 0
    assert len(avisos) == 1 and avisos[0][0] == int(Nivel.AVISO) and avisos[0][2] == "ping_sin_url"


def test_ping_cada_60_s_sin_bloquear_y_sin_solapar(reloj: RelojSimulado) -> None:
    """R-J-05: el GET va en un hilo (timeout 5 s): `tocar_si_toca` vuelve al instante y no lanza otro con uno en curso."""
    abrir = AbrirPing(tarda_s=0.3)
    ping = vg.PingExterno(URL_PING, reloj, cada_s=60, abrir=abrir)
    t0 = time.monotonic()
    ping.tocar_si_toca(1000.0)
    assert time.monotonic() - t0 < 0.1                           # no bloquea al vigilante (latido < 3 s)
    ping.tocar_si_toca(1070.0)                                   # ya tocaría, pero hay uno en curso: no se solapa
    assert ping.esperar(2.0)
    abrir.tarda_s = 0.0
    assert abrir.llamadas == [(URL_PING, vg.PING_TIMEOUT_S)] and ping.enviados == 1 and ping.fallos == 0
    ping.tocar_si_toca(1059.9)                                   # < 60 s desde el último intento (1000)
    assert ping.esperar(2.0) and len(abrir.llamadas) == 1
    ping.tocar_si_toca(1060.0)
    assert ping.esperar(2.0) and len(abrir.llamadas) == 2 and ping.enviados == 2
    assert ping.ultimo_ok_en == pytest.approx(reloj.epoch())


@pytest.mark.parametrize("abrir", [AbrirPing(falla=OSError("red caída")), AbrirPing(status=500)],
                         ids=["R-J-05-excepcion", "R-J-05-estado-500"])
def test_ping_fallos_seguidos_avisan_una_vez_por_racha(reloj: RelojSimulado, abrir: AbrirPing) -> None:
    """R-J-05: un GET que falla nunca lanza; a los 3 seguidos, aviso 2 una vez; un ping bueno reinicia la racha."""
    avisos: list[tuple] = []
    ping = vg.PingExterno(URL_PING, reloj, cada_s=1, abrir=abrir, fallos_alarma=3,
                          al_aviso=lambda n, t, c: avisos.append((n, t, c)))
    for i in range(5):
        ping.tocar_si_toca(1000.0 + i)
        assert ping.esperar(2.0)
    assert ping.fallos == 5 and ping.fallos_seguidos == 5 and ping.enviados == 0
    assert [a[2] for a in avisos] == ["ping_fallos"] and avisos[0][0] == int(Nivel.AVISO)
    abrir.falla, abrir.status = None, 204
    ping.tocar_si_toca(1010.0)
    assert ping.esperar(2.0) and ping.fallos_seguidos == 0 and ping.enviados == 1
    abrir.status = 503
    for i in range(3):
        ping.tocar_si_toca(1020.0 + i)
        assert ping.esperar(2.0)
    assert [a[2] for a in avisos] == ["ping_fallos", "ping_fallos"]   # racha nueva, aviso nuevo


def test_ping_nunca_escribe_la_url_en_el_log(reloj: RelojSimulado, caplog: pytest.LogCaptureFixture) -> None:
    """R-Q-01: la URL del ping lleva el identificador del servicio; ni el log ni los avisos la muestran."""
    avisos: list[tuple] = []
    abrir = AbrirPing(falla=OSError(f"no se pudo abrir {URL_PING}"))
    ping = vg.PingExterno(URL_PING, reloj, cada_s=1, abrir=abrir, fallos_alarma=1,
                          al_aviso=lambda n, t, c: avisos.append((n, t, c)))
    with caplog.at_level(logging.DEBUG, logger="app.bot_das.vigilante"):
        ping.tocar_si_toca(1000.0)
        assert ping.esperar(2.0)
    assert caplog.records, "el fallo debe quedar en el log"
    assert all(URL_PING not in r.getMessage() for r in caplog.records)
    assert avisos and all(URL_PING not in a[1] for a in avisos)
    assert URL_PING not in (ping.ultimo_error or "")


@pytest.mark.parametrize("kw", [{"cada_s": 0}, {"cada_s": float("nan")}, {"timeout_s": -1}, {"fallos_alarma": 0},
                                {"abrir": "no-callable"}, {"al_aviso": 3}],
                         ids=["cada-0", "cada-nan", "timeout-neg", "fallos-0", "abrir", "al-aviso"])
def test_ping_rechaza_parametros_imposibles(reloj: RelojSimulado, kw: dict) -> None:
    with pytest.raises((ValueError, TypeError)):
        vg.PingExterno(URL_PING, reloj, **kw)


def test_seguidor_lee_solo_lineas_completas_y_relee_tras_truncar(dir_bot: Path, reloj: RelojSimulado) -> None:
    """Riesgo 22: el vigilante sigue el diario del ejecutor por bytes; la línea a medio escribir espera a estar entera."""
    lector = LectorDiario(dir_bot / "diario")
    seguidor = vg._SeguidorDiario(lector, "ejecutor")
    assert seguidor.leer(HOY) == []                                # sin fichero todavía
    d = Diario(dir_bot / "diario", reloj, "ejecutor", VERSION, Fase.CANARIO)
    d.abrir_dia(HOY)
    d.anotar("lote", ticker=TICKER, lote_id=LOTE_ID, nivel_stop="4.00")
    d.cerrar()
    assert [r.tipo for r in seguidor.leer(HOY)] == ["arranque", "lote"]
    assert seguidor.leer(HOY) == []
    ruta = lector.ruta(HOY, "ejecutor")
    linea = json.dumps({"v": 1, "seq": 3, "t": "2026-09-25T09:30:01.000-04:00", "proceso": "ejecutor",
                        "tipo": "pausa", "ticker": TICKER, "datos": {"motivo": "x"}})
    with open(ruta, "a", encoding="utf-8", newline="\n") as f:
        f.write(linea[:20])
    assert seguidor.leer(HOY) == []                                # a medias: no es un registro
    with open(ruta, "a", encoding="utf-8", newline="\n") as f:
        f.write(linea[20:] + "\n")
    assert [r.tipo for r in seguidor.leer(HOY)] == ["pausa"]
    ruta.write_text(linea + "\n", encoding="utf-8")               # sustituido por uno más corto: se relee
    assert [r.tipo for r in seguidor.leer(HOY)] == ["pausa"]


@pytest.mark.parametrize("cuando, dentro", [
    (datetime(2026, 9, 25, 3, 54, tzinfo=ET), False), (datetime(2026, 9, 25, 3, 55, tzinfo=ET), True),
    (datetime(2026, 9, 25, 19, 59, tzinfo=ET), True), (datetime(2026, 9, 25, 20, 0, tzinfo=ET), False),
    (datetime(2026, 9, 26, 10, 0, tzinfo=ET), False)],
    ids=["R-L-01-antes-de-encender", "R-L-01-encender", "R-J-05-tarde", "R-J-05-20h", "R-L-01-sabado"])
def test_ventana_por_horario_sin_red(cfg: Config, cuando: datetime, dentro: bool) -> None:
    """R-L-01 / R-J-05: por defecto se pinga de lunes a viernes de `horario.encender` (03:55) a las 20:00."""
    assert vg._ventana_por_horario(cfg)(cuando) is dentro


def test_el_constructor_rechaza_piezas_equivocadas(montar) -> None:
    m = montar(arrancar=False)
    v = m.v
    base = dict(cfg=v.cfg, watch=v.watch, abrir_accion=lambda: None, lector=v._lector, diario=v.diario,
                avisos=m.avisos, reloj=m.reloj, latido=v._latido, cerrojo=v._cerrojo,
                ruta_latido_ejecutor=v._ruta_latido_ejecutor, ping=None, ruta_orden_supervisor=v._ruta_orden_supervisor)
    for cambio in ({"cfg": {}}, {"watch": object()}, {"abrir_accion": 3}, {"lector": object()},
                   {"diario": object()}, {"avisos": object()}, {"reloj": object()}, {"latido": object()},
                   {"cerrojo": object()}, {"ping": object()}):
        with pytest.raises(TypeError):
            vg.VigilanteDAS(**{**base, **cambio})
    with pytest.raises(ValueError):
        vg.VigilanteDAS(**base, periodo_s=0)
    with pytest.raises(RuntimeError):
        v.paso(0.0)                                             # sin arrancar no hay bucle
    assert v.arrancar() == vg.CODIGO_OK
    with pytest.raises(RuntimeError):
        v.arrancar()


# ═══════════════════════════ 2. contra el simulador ══════════════════════
def _montar_ejecutor(cfg: Config, reloj: RelojSimulado, dir_bot: Path, direccion: tuple[str, int]) -> Any:
    """Un ejecutor REAL (Decisor + ClienteDAS normal + diario) con dobles sin red para fuente, avisos, Massive y calendario."""
    ej = pytest.importorskip("app.bot_das.ejecutor")
    decisor_mod = pytest.importorskip("app.bot_das.decisor")
    from app.bot_das.mercado_das import MercadoDAS
    from app.bot_das.reglas import rechazos
    from app.bot_das.tokens import GeneradorTokens

    buzon = ej.Buzon()
    host, puerto = direccion
    cliente = ClienteDAS(host, puerto, USUARIO, CLAVE_DAS, CUENTA, False, False, buzon.al_mensaje, buzon.al_estado,
                         reloj, al_aviso=buzon.al_aviso, al_caida_hilo=buzon.al_caida_hilo)
    diario = Diario(dir_bot / "diario", reloj, "ejecutor", VERSION, cfg.fase)
    mercado = MercadoDAS(reloj)
    catalogo = rechazos.cargar_catalogo(rechazos.RUTA_CATALOGO)

    def fabrica(estado):
        tokens = GeneradorTokens(Origen.EJECUTOR, estado.dia, estado.ultimo_seq_token)
        return decisor_mod.Decisor(cfg, estado, mercado, ReferenciaFalsa(), tokens, catalogo,
                                   lambda: diario.degradado, calendario=CalendarioPrueba())

    estado_dir = dir_bot / "estado"
    return ej.Ejecutor(cfg, cliente, FuenteManual(), diario, AvisosGrabados(), mercado, fabrica, reloj,
                       Latido(estado_dir / ej.NOMBRE_LATIDO, reloj), CerrojoInstancia(estado_dir / ej.NOMBRE_CERROJO),
                       [], None, estado_dir, buzon=buzon, hash_motor=lambda base: cfg.motor_hash,
                       medir_desvio=lambda: 0.0, espera_reconciliacion_s=5.0, espera_avisos_s=0.1)


@pytest.mark.parametrize("latido", ["ausente", "viejo"], ids=["R-C-07-plan-B-sin-latido", "R-C-07-plan-B-latido-viejo"])
def test_r_c_07_plan_b_repone_el_par_en_menos_de_2_s_y_el_ejecutor_lo_adopta(
        montar, cfg_canario: Config, reloj: RelojSimulado, dir_bot: Path, libro: Any, simulador: Any,
        direccion_simulador: tuple[str, int], latido: str) -> None:
    """R-C-07 plan B + R-C-08 + F13: posición corta sin stops y el ejecutor callado ⇒ el vigilante pone principal +
    emergencia (+3/+13/+63 sobre L) en < 2 s por su conexión de acción, con write-ahead en SU diario; después un
    ejecutor real arranca, reconcilia y ADOPTA esos stops (0 órdenes nuevas, ninguna cancelada)."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    libro.cotizar(TICKER, D("3.44"), D("3.46"), last=D("3.45"), volumen=500_000)
    escribir_diario_ejecutor(dir_bot, reloj)
    if latido == "viejo":
        escribir_latido_ejecutor(dir_bot, reloj.epoch() - 60)
    ruta_ejecutor = LectorDiario(dir_bot / "diario").ruta(HOY, "ejecutor")
    bytes_ejecutor = ruta_ejecutor.read_bytes()
    m = montar(arrancar=False)
    resultado: list[int] = []
    hilo = threading.Thread(target=lambda: resultado.append(m.v.correr()), name="vigilante-prueba", daemon=True)
    t0 = time.monotonic()
    hilo.start()
    try:
        while len(stops_vivos(libro)) < 2:
            assert time.monotonic() - t0 < PLAZO_S, f"el par no llegó; DAS recibió {simulador.recibidas()[-6:]}"
            time.sleep(0.01)
        repuesto_s = time.monotonic() - t0
        assert repuesto_s < 2.0, f"el plan B tardó {repuesto_s:.2f} s"
        principal, emergencia = sorted(stops_vivos(libro), key=lambda o: o["stop"])
        assert (principal["lado"], principal["qty"], principal["stop"], principal["precio"], principal["ruta"]) == \
            ("B", 100, D("4"), D("4.12"), "STOP")                                     # R-C-01 v3: L y L·1,03
        assert (emergencia["lado"], emergencia["qty"], emergencia["stop"], emergencia["precio"]) == \
            ("B", 100, D("4.52"), D("6.52"))                                          # L·1,13 y L·1,63
        tokens_vigilante = {principal["token"], emergencia["token"]}
        assert all(descomponer(t)[0] is Origen.VIGILANTE for t in tokens_vigilante)   # quién la puso (R-C-07)
        assert m.abrir.llamadas == 1
        assert ruta_ejecutor.read_bytes() == bytes_ejecutor                           # corrección 3: diarios separados
        # ── el ejecutor arranca (F12) y adopta ──
        e = _montar_ejecutor(cfg_canario, reloj, dir_bot, direccion_simulador)
        try:
            assert e.arrancar() == 0
            assert e.decisor.estado.reconciliacion_ok_en is not None
            fin = time.monotonic() + 1.5
            while time.monotonic() < fin:
                assert e.paso(0.02) is None
            del_ejecutor = [linea for linea in neworders(simulador.recibidas())
                            if descomponer(int(linea.split()[1]))[0] is not Origen.VIGILANTE]
            assert del_ejecutor == [], f"el ejecutor no debía mandar órdenes nuevas: {del_ejecutor}"
            assert {o["token"] for o in stops_vivos(libro)} == tokens_vigilante      # adoptados, no sustituidos
            ids = {o["id"] for o in libro.ordenes() if o["token"] in tokens_vigilante}
            tocadas = [linea for linea in simulador.recibidas() if linea.split()[0] in ("CANCEL", "REPLACE")
                       and linea.split()[1] in {str(i) for i in ids}]
            assert tocadas == []
            adoptadas = {t: e.decisor.estado.ordenes.get(t) for t in tokens_vigilante}
            assert all(o is not None and o.origen is Origen.VIGILANTE for o in adoptadas.values())
            assert {o.proposito for o in adoptadas.values()} == {Proposito.STOP_PRINCIPAL, Proposito.STOP_EMERGENCIA}
        finally:
            e.parar()
    finally:
        m.v.pedir_parada("fin del test")
        hilo.join(5.0)
    assert resultado == [vg.CODIGO_OK] and not hilo.is_alive()
    regs = m.regs()
    intenciones = de_tipo(regs, "orden_intencion")
    enviadas = de_tipo(regs, "orden_enviada")
    assert {r.datos["token"] for r in intenciones} == tokens_vigilante == {r.datos["token"] for r in enviadas}
    for r in intenciones:                                                             # M6: intención ANTES del envío
        envio = next(x for x in enviadas if x.datos["token"] == r.datos["token"])
        assert r.seq < envio.seq and r.proceso == "vigilante"
    acciona = [r for r in de_tipo(regs, "vigilancia") if r.datos.get("actua")]
    assert acciona and acciona[0].seq < min(r.seq for r in intenciones)                # la anotación va delante
    assert (dir_bot / "diario" / nombre_fichero("vigilante", HOY)).is_file()
    assert simulador.errores() == []


def test_r_c_08_con_el_ejecutor_vivo_espera_el_plazo_de_descubierta(montar, reloj: RelojSimulado, dir_bot: Path,
                                                                    libro: Any) -> None:
    """R-C-08.2 (cerrojo sin lock): con el ejecutor latiendo no se actúa aunque falte el stop, hasta que la posición lleve
    más de `plan_b_descubierta_s` (5 s) descubierta; entonces sí se repone (y solo se anota antes)."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    m = montar()
    m.listo()
    m.pasadas(3)
    assert neworders(m.recibidas()) == [] and m.abrir.llamadas == 0
    anotaciones = de_tipo(m.regs(), "vigilancia")
    assert len(anotaciones) == 1 and anotaciones[0].datos["actua"] is False           # sin ruido: una sola línea
    reloj.avanzar(4.0)
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    m.pasadas(2)
    assert neworders(m.recibidas()) == []                                             # 4 s < 5 s
    reloj.avanzar(1.5)
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    m.bombear(lambda: len(stops_vivos(libro)) == 2, "par repuesto tras 5 s descubierta")
    assert len(neworders(m.recibidas(), TICKER)) == 2


def test_correccion16_sin_conexion_de_accion_pide_relanzar_el_ejecutor(montar, reloj: RelojSimulado, dir_bot: Path,
                                                                       libro: Any) -> None:
    """Corrección 16 / riesgo 31: DAS no admite la segunda conexión normal ⇒ ni una orden, aviso 3 y
    `{"relanzar": "ejecutor"}` en orden_supervisor.jsonl (como mucho una vez cada 10 s)."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    m = montar(accion=False)
    m.listo()
    m.pasadas(4)
    assert neworders(m.recibidas()) == []
    assert m.abrir.llamadas == 1                                   # no se reintenta antes de REABRIR_ACCION_S
    ruta = dir_bot / "estado" / vg.NOMBRE_ORDEN_SUPERVISOR
    lineas = [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()]
    assert len(lineas) == 1
    assert lineas[0]["relanzar"] == "ejecutor" and lineas[0]["proceso"] == "vigilante"
    assert lineas[0]["peticion"] == "relanzar ejecutor" and "parar" not in lineas[0]
    assert m.avisos.con_clave("vigilante_sin_envio") and m.avisos.con_clave("vigilante_sin_envio")[0].nivel is Nivel.MAXIMO
    assert m.avisos.con_clave("vigilante_sin_envio")[0].texto.startswith("[CANARIO]")   # R-O-03: la fase delante
    bloqueadas = [r for r in de_tipo(m.regs(), "vigilancia") if r.datos.get("bloqueado")]
    assert bloqueadas and not bloqueadas[0].datos["actua"]
    assert m.v.ultimo_seq_token == 0                               # bloqueado no gasta tokens
    reloj.avanzar(vg.PETICION_REPETIR_S + 0.5)
    m.pasadas(1)
    assert len(ruta.read_text(encoding="utf-8").splitlines()) == 2
    assert de_tipo(m.regs(), "peticion_supervisor")


def test_r_o_03_sombra_no_envia_ni_un_mutante_ni_abre_la_accion(montar, cfg: Config, reloj: RelojSimulado,
                                                                 dir_bot: Path, libro: Any) -> None:
    """R-O-03 / §9: en SOMBRA el vigilante no abre la conexión de acción ni manda un mutante; lo que habría hecho
    queda como `vigilancia_simulada` (que `reconstruir` no convierte en órdenes) y no se repite cada segundo."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    m = montar(config=dataclasses.replace(cfg, fase=Fase.SOMBRA))
    assert m.v.sombra
    m.listo()
    m.bombear(lambda: len(de_tipo(m.regs(), "vigilancia_simulada")) >= 2, "orden simulada")
    m.pasadas(3)
    assert m.abrir.llamadas == 0
    assert not [linea for linea in m.recibidas() if protocolo.es_mutante(linea)]
    assert stops_vivos(libro) == []
    simuladas = de_tipo(m.regs(), "vigilancia_simulada")
    assert len(simuladas) == 2 and {r.datos["proposito"] for r in simuladas} == {"stop_principal", "stop_emergencia"}
    assert not de_tipo(m.regs(), "orden_intencion") and not de_tipo(m.regs(), "pos")
    assert de_tipo(m.regs(), "pos_watch")                        # la cuenta real, sin contaminar la reconstrucción


def test_r_c_03_un_rechazo_respeta_la_separacion_y_luego_repone(montar, reloj: RelojSimulado, dir_bot: Path,
                                                                libro: Any, simulador: Any) -> None:
    """R-C-03 / riesgo 11: DAS rechaza el stop del vigilante ⇒ diario `orden_act`, aviso 3 y NINGÚN reintento hasta
    `separacion_reintentos_s` (2 s); pasado el plazo se repone y queda aceptado."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    libro.rechazar_siguiente("Invalid stop price")
    m = montar()
    m.listo()
    m.bombear(lambda: any(r.datos.get("accion") == "Send_Rej" for r in de_tipo(m.regs(), "orden_act"))
              and len(stops_vivos(libro)) == 1, "un rechazo y un stop aceptado")
    m.pasadas(5)
    assert len(neworders(m.recibidas())) == 2                   # separación: no se reintenta todavía
    assert m.avisos.con_clave(f"vigilante_rechazo:{TICKER}")[0].nivel is Nivel.MAXIMO
    assert de_tipo(m.regs(), "vigilancia_retenida")
    reloj.avanzar(2.5)
    m.bombear(lambda: len(stops_vivos(libro)) == 2, "reintento tras la separación")
    assert len(neworders(m.recibidas())) == 3
    assert simulador.errores() == []


def test_r_c_03_rechazos_agotados_dejan_el_ticker_en_control_humano(montar, reloj: RelojSimulado, dir_bot: Path,
                                                                     libro: Any) -> None:
    """R-C-03 / riesgo 11: tras `stops.reintentos` (5) rechazos el vigilante deja de mandar y avisa CONTROL HUMANO."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    for _ in range(20):
        libro.rechazar_siguiente("Invalid stop price")
    m = montar()
    m.listo()
    for ronda in range(3):
        m.bombear(lambda r=ronda: len([x for x in de_tipo(m.regs(), "orden_act") if x.datos.get("accion") == "Send_Rej"])
                  >= 2 * (r + 1), f"rechazos de la ronda {ronda}")
        reloj.avanzar(2.5)
    m.pasadas(5)
    reloj.avanzar(2.5)
    m.pasadas(5)
    assert len(neworders(m.recibidas())) == 6                   # 3 rondas × (principal + emergencia) y se para
    humano = m.avisos.con_clave(f"vigilante_control_humano:{TICKER}")
    assert humano and humano[0].nivel is Nivel.MAXIMO and "CONTROL HUMANO" in humano[0].texto


def test_r_c_10_4_posicion_sin_lote_recibe_proteccion_y_aviso_3(montar, dir_bot: Path, libro: Any) -> None:
    """R-C-10 caso 4 (y fixture del diario del vigilante): 200 largas que ningún diario conoce ⇒ STOPLMTP de venta al
    25 % bajo el precio (7,50 / 7,27 sobre 10,00) con token del vigilante y aviso 3."""
    libro.sembrar_posicion("QRS", 200, D("10.00"))
    m = montar()
    m.listo()
    m.bombear(lambda: stops_vivos(libro, "QRS"), "protección de QRS")
    (proteccion,) = stops_vivos(libro, "QRS")
    assert (proteccion["lado"], proteccion["qty"], proteccion["stop"], proteccion["precio"]) == \
        ("S", 200, D("7.5"), D("7.27"))
    assert descomponer(proteccion["token"])[0] is Origen.VIGILANTE
    aviso = m.avisos.con_clave("vigilante_desconocida:QRS")
    assert aviso and aviso[0].nivel is Nivel.MAXIMO
    intencion = [r for r in de_tipo(m.regs(), "orden_intencion") if r.datos.get("proposito") == "stop_proteccion"]
    assert intencion and intencion[0].datos["token"] == proteccion["token"]
    m.pasadas(3)
    assert len(neworders(m.recibidas(), "QRS")) == 1            # riesgo 11: no se duplica


def test_r_h_02_locates_repetidos_se_deshabilitan_una_sola_vez(montar, reloj: RelojSimulado, dir_bot: Path) -> None:
    """R-H-02: dos compras Located no pedidas del mismo ticker-estrategia ⇒ aviso 3 + `locates_deshabilitar` en el
    diario del vigilante; la pasada siguiente lo lee de su propio diario y no lo repite."""
    def locates(d: Diario) -> None:
        for id_das in (9101, 9102):
            d.anotar("locate_estado", ticker=TICKER, strategy_id=SID, id_das=id_das, estado="Located",
                     localizadas=100, coste_nuevo="1.00", precio_accion="0.01")

    escribir_diario_ejecutor(dir_bot, reloj, extra=locates)
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    m = montar()
    m.listo()
    m.bombear(lambda: de_tipo(m.regs(), "locates_deshabilitar"), "locates deshabilitados")
    reloj.avanzar(vg.AVISO_REPETIR_S + 1)
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    m.pasadas(4)
    assert len(de_tipo(m.regs(), "locates_deshabilitar")) == 1
    assert len(m.avisos.con_clave("vigilante_locates")) == 1


def test_r_l_01_la_orden_parar_del_supervisor(montar, dir_bot: Path) -> None:
    """§6.2.5: un «parar» anterior al arranque no para; uno para el ejecutor tampoco; uno para el vigilante sí (0)."""
    ruta = dir_bot / "estado" / vg.NOMBRE_ORDEN_SUPERVISOR
    ruta.write_text(json.dumps({"parar": True}) + "\n", encoding="utf-8")
    m = montar()
    m.pasadas(2)
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(json.dumps({"parar": True, "para": "ejecutor"}) + "\n")
    m.pasadas(2)
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(json.dumps({"parar": True, "para": "vigilante"}) + "\n")
    assert m.v.paso(0.0) == vg.CODIGO_OK
    assert m.v.correr() == vg.CODIGO_OK
    assert de_tipo(m.regs(), "orden_supervisor")


def test_r_j_04_c_doble_instancia_no_arranca_ni_toca_el_diario(montar, dir_bot: Path) -> None:
    """R-J-04 c / F11 e: con el cerrojo tomado la segunda instancia sale con 3, avisa (3) y no escribe el diario."""
    primera = montar()
    ruta = primera.v.diario.ruta
    antes = ruta.read_bytes()
    segunda = montar(arrancar=False)
    assert segunda.v.arrancar() == vg.CODIGO_DOBLE_INSTANCIA
    assert segunda.avisos.con_clave("arranque:doble_instancia")[0].nivel is Nivel.MAXIMO
    segunda.v.parar()
    assert ruta.read_bytes() == antes and primera.v._cerrojo.tomado
    assert primera.v.paso(0.0, forzar=True) is None


def test_injerto_8_11_el_latido_se_retiene_con_el_watch_sordo(montar, reloj: RelojSimulado, dir_bot: Path) -> None:
    """Injerto §8.11 / R-J-04 b: con el lector del watch muerto el vigilante NO late (el supervisor lo relanzará)."""
    watch = WatchSordo()
    m = montar(watch=watch)
    latido = m.v._latido
    assert latido.escrituras == 1                               # el de arrancar
    reloj.avanzar(1.5)
    m.pasadas(2)
    assert latido.escrituras == 1
    retenido = de_tipo(m.regs(), "latido_retenido")
    assert len(retenido) == 1 and retenido[0].datos["hilos"] == {"watch": False, "avisos": True}
    watch.hilos_vivos = True
    reloj.avanzar(1.5)
    m.pasadas(1)
    assert latido.escrituras == 2
    assert Latido.edad(dir_bot / "estado" / vg.NOMBRE_LATIDO, reloj.epoch()) == pytest.approx(0.0)
    assert m.avisos.con_clave("vigilante_watch")                # sin DAS: aviso 2 una vez


def test_r_j_02_watch_caido_no_vigila_avisa_y_reconecta(montar, reloj: RelojSimulado, dir_bot: Path, libro: Any,
                                                         simulador: Any) -> None:
    """R-J-02 / R-C-08: el watch cae ⇒ aviso 2, sin vigilancia (libro viejo) y reconexión por plan; al volver, volcado
    nuevo, aviso de recuperación y la vigilancia sigue (repone el par)."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    m = montar(plan=PlanReconexion((0.05,), 0.05))
    m.listo()
    simulador.cortar("watch")
    m.bombear(lambda: m.avisos.con_clave("vigilante_watch"), "aviso de caída del watch")
    assert m.avisos.con_clave("vigilante_watch")[0].nivel is Nivel.AVISO
    m.bombear(lambda: m.avisos.con_clave("vigilante_watch_vuelve"), "reconexión del watch")
    m.listo()
    conexiones = [r for r in de_tipo(m.regs(), "das_conexion") if r.datos.get("conexion") == "watch"
                  and "conectado" in r.datos]
    assert [r.datos["conectado"] for r in conexiones][-2:] == [False, True]
    escribir_latido_ejecutor(dir_bot, reloj.epoch() - 30)       # el ejecutor muere: el plan B sigue funcionando
    m.bombear(lambda: len(stops_vivos(libro)) == 2, "par repuesto tras reconectar")


def test_r_j_05_el_ping_solo_sale_con_watch_y_ejecutor_vivos(montar, reloj: RelojSimulado, dir_bot: Path) -> None:
    """R-J-05: el ping sale si el watch vive, el ejecutor late y se está dentro de la ventana; si no, silencio (alarma)."""
    abrir = AbrirPing()
    dentro = {"valor": True}
    ping = vg.PingExterno(URL_PING, reloj, cada_s=60, abrir=abrir)
    m = montar(ping=ping, dentro=lambda ahora_et: dentro["valor"])
    m.listo()
    m.pasadas(1)
    assert ping.esperar(2.0) and abrir.llamadas == []           # sin latido del ejecutor: silencio
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    m.pasadas(1)
    assert ping.esperar(2.0) and len(abrir.llamadas) == 1
    reloj.avanzar(61)
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    dentro["valor"] = False
    m.pasadas(1)
    assert ping.esperar(2.0) and len(abrir.llamadas) == 1       # fuera de la ventana (R-L-01)
    dentro["valor"] = True
    m.pasadas(1)
    assert ping.esperar(2.0) and len(abrir.llamadas) == 2


def test_r_j_05_sin_url_de_ping_avisa_al_arrancar_una_sola_vez(montar, reloj: RelojSimulado, dir_bot: Path) -> None:
    """R-J-05: sin BOT_DAS_PING_URL el vigilante lo avisa (2, con la fase delante) al arrancar, y no lo repite."""
    cola = vg.ColaVigilante()
    ping = vg.PingExterno("", reloj, al_aviso=cola.al_aviso_nivel)
    m = montar(ping=ping, cola=cola)
    aviso = m.avisos.con_clave("ping_sin_url")
    assert len(aviso) == 1 and aviso[0].nivel is Nivel.AVISO and aviso[0].texto.startswith("[CANARIO]")
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    m.listo()
    reloj.avanzar(vg.AVISO_REPETIR_S + 1)
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    m.pasadas(3)
    assert len(m.avisos.con_clave("ping_sin_url")) == 1 and ping.intentos == 0
    assert [r.datos["clave"] for r in de_tipo(m.regs(), "aviso")].count("ping_sin_url") == 1


def test_r_c_08_c_el_ejecutor_callado_se_avisa_pasado_el_plazo(montar, reloj: RelojSimulado, dir_bot: Path) -> None:
    """R-C-08 (c) «y viceversa»: el ejecutor sin latido se anota al instante y se avisa (2) si dura > 30 s."""
    m = montar()
    m.listo()
    m.pasadas(2)
    assert len(de_tipo(m.regs(), "ejecutor_callado")) == 1 and not m.avisos.con_clave("vigilante_ejecutor_callado")
    reloj.avanzar(vg.EJECUTOR_CALLADO_AVISO_S + 1)
    m.pasadas(2)
    assert len(m.avisos.con_clave("vigilante_ejecutor_callado")) == 1
    escribir_latido_ejecutor(dir_bot, reloj.epoch())
    m.pasadas(1)
    assert de_tipo(m.regs(), "ejecutor_late")


def test_h5_una_pasada_que_revienta_no_para_la_vigilancia(montar, monkeypatch: pytest.MonkeyPatch,
                                                          dir_bot: Path, libro: Any, reloj: RelojSimulado) -> None:
    """H-5: una excepción en la pasada se anota (con traza) y avisa (2); la vigilancia sigue en la pasada siguiente."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    original = vg.vigilancia.comprobar
    llamadas = {"n": 0}

    def rota(*a: Any, **k: Any) -> Any:
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise ZeroDivisionError("fallo inventado")
        return original(*a, **k)

    monkeypatch.setattr(vg.vigilancia, "comprobar", rota)     # antes del volcado: la primera pasada útil revienta
    m = montar()
    m.bombear(lambda: len(stops_vivos(libro)) == 2, "vigilancia tras la excepción")
    excepciones = de_tipo(m.regs(), "excepcion")
    assert len(excepciones) == 1 and "ZeroDivisionError" in excepciones[0].datos["traceback"]
    assert m.avisos.con_clave("excepcion_vigilante:pasada")


def test_tokens_del_vigilante_siguen_tras_un_reinicio(montar, reloj: RelojSimulado, dir_bot: Path, libro: Any) -> None:
    """H-2 / R-C-07: el vigilante relanzado continúa su secuencia de tokens desde los diarios (nunca repite uno)."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    primera = montar()
    primera.listo()
    primera.bombear(lambda: len(stops_vivos(libro)) == 2, "par del primer vigilante")
    usados = {o["token"] for o in stops_vivos(libro)}
    primera.v.parar()
    primera.abrir.cerrar()
    segunda = montar()
    assert segunda.v.ultimo_seq_token == max(descomponer(t)[2] for t in usados)


# ═══════════════════════════ 3. construcción y main ══════════════════════
def _entorno_das(monkeypatch: pytest.MonkeyPatch, puerto: int = 50997) -> None:
    for nombre, valor in {"DAS_API_HOST": "127.0.0.1", "DAS_API_PORT": str(puerto), "DAS_USUARIO": USUARIO,
                          "DAS_CLAVE": CLAVE_DAS, "DAS_CUENTA": CUENTA}.items():
        monkeypatch.setenv(nombre, valor)


def test_construir_canario_exige_la_llave_de_entorno(cfg_canario: Config, reloj: RelojSimulado,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Corrección 15: en CANARIO/REAL el vigilante tampoco se construye sin BOT_DAS_PERMITIR_ORDENES=1."""
    _entorno_das(monkeypatch)
    with pytest.raises(RuntimeError, match="BOT_DAS_PERMITIR_ORDENES"):
        vg.construir_desde_env(cfg_canario, reloj, canales=[])
    monkeypatch.setenv("BOT_DAS_PERMITIR_ORDENES", "1")
    v = vg.construir_desde_env(cfg_canario, reloj, canales=[])
    assert not v.sombra and v.watch.watch and v.watch.solo_lectura


def test_construir_sombra_no_abre_red_ni_hilos_ni_escribe_y_tapa_la_url_del_ping(
        cfg: Config, reloj: RelojSimulado, dir_bot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§3.27 / R-Q-01: construir no conecta ni arranca hilos ni escribe; en sombra `abrir_accion` no abre nada; la URL
    del ping va al `FiltroSecretos` del diario."""
    _entorno_das(monkeypatch)
    monkeypatch.setenv(vg.ENV_PING_URL, URL_PING)
    hilos = threading.active_count()
    v = vg.construir_desde_env(cfg, reloj, canales=[])
    assert threading.active_count() == hilos
    assert list((dir_bot / "diario").iterdir()) == []
    assert v.sombra and v.watch.watch and v.watch.solo_lectura and v.ping is not None and v.ping.activo
    assert v._abrir_accion() is None                            # tercer candado de la sombra
    v.diario.anotar("prueba", texto=f"la url es {URL_PING}")
    v.diario.cerrar()
    texto = v.diario.ruta.read_text(encoding="utf-8")
    assert URL_PING not in texto and "*****" in texto


def test_construir_sin_entorno_de_das_lanza(cfg: Config, reloj: RelojSimulado) -> None:
    with pytest.raises(RuntimeError):
        vg.construir_desde_env(cfg, reloj, canales=[])


def _main_aislado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`main` sin el `.env` real y con su propio BOT_DAS_DIR (aunque faltara el conftest, nada va a D:\\bot_senales)."""
    raiz = tmp_path / "bot_main"
    monkeypatch.setattr(vg, "RUTA_DOTENV", tmp_path / "no-existe.env")
    monkeypatch.setenv(vg.ENV_DIR, str(raiz))
    return raiz


def test_main_sin_cuenta_sale_con_5_sin_tocar_el_env_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raiz = _main_aislado(tmp_path, monkeypatch)
    assert vg.main([]) == vg.CODIGO_CONFIG
    assert (raiz / "logs").is_dir()                              # el log va al BOT_DAS_DIR del test


def test_main_con_config_inexistente_sale_con_5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _main_aislado(tmp_path, monkeypatch)
    monkeypatch.setenv("DAS_CUENTA", CUENTA)
    assert vg.main(["--config", str(tmp_path / "no-existe.json")]) == vg.CODIGO_CONFIG


class WatchMudo:
    """Watch que conecta pero NO manda volcado tras el LOGIN (¿el DAS real?, paso 7): contesta solo a los GET."""

    def __init__(self, cola: vg.ColaVigilante) -> None:
        self.cola = cola
        self.conectado = False
        self.hilos_vivos = True
        self.enviadas: list[str] = []

    def conectar(self) -> bool:
        self.conectado = True
        self.cola.al_estado(True, "conectado (mudo)")
        return True

    def cerrar(self) -> None:
        self.conectado = False

    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> None:
        self.enviadas.append(linea)
        fin = {"GET POSITIONS": "#POSEND", "GET ORDERS": "#OrderEnd"}.get(linea)
        if fin is not None:
            self.cola.al_mensaje(protocolo.parsear(fin))


def test_r_c_08_sin_volcado_del_login_se_piden_posiciones_y_ordenes_una_vez(montar) -> None:
    """Paso 7 de comprobar_das: si el watch no manda volcado, a `PEDIR_VOLCADO_S` se piden GET POSITIONS y GET ORDERS
    (una vez por conexión) y con sus respuestas el libro queda listo; antes no se vigila."""
    cola = vg.ColaVigilante()
    watch = WatchMudo(cola)
    m = montar(watch=watch, cola=cola)
    m.pasadas(1)
    assert watch.enviadas == [] and not m.v._watch_listo()
    m.bombear(lambda: watch.enviadas, "GET del volcado", plazo_s=3.0)
    m.pasadas(3)
    assert watch.enviadas == ["GET POSITIONS", "GET ORDERS"]
    assert m.v._watch_listo() and de_tipo(m.regs(), "volcado_pedido")


def test_importar_no_trae_pandas_ni_arranca_hilos() -> None:
    """Riesgo 29 / §3: el vigilante es ligero y no depende del ejecutor ni del decisor."""
    import subprocess
    import sys
    codigo = ("import sys, threading; import app.bot_das.vigilante; "
              "print('pandas' in sys.modules, 'app.bot_das.ejecutor' in sys.modules, "
              "'app.bot_das.decisor' in sys.modules, threading.active_count())")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=str(Path(__file__).resolve().parents[2]),
                            capture_output=True, text=True, timeout=60)
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.split() == ["False", "False", "False", "1"]


class ClienteGrabador:
    """Conexión de acción que acepta todo y no lo manda a ningún sitio: DAS «no contesta» (riesgo 11)."""

    def __init__(self) -> None:
        self.conectado = True
        self.lineas: list[str] = []

    def conectar(self) -> bool:
        self.conectado = True
        return True

    def cerrar(self) -> None:
        self.conectado = False

    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> None:
        self.lineas.append(linea)


def _sembrar_orden(simulador: Any, linea: str) -> int:
    """Una orden que ya estaba en DAS antes del LOGIN del vigilante (sale en su volcado). Devuelve su id."""
    salida = simulador.emparejador.recibir(linea)
    assert any(" Accept " in x for x in salida), salida
    return max(o["id"] for o in simulador.libro.ordenes())


def test_riesgo_11_lo_enviado_sin_eco_no_se_duplica_y_caduca(montar, reloj: RelojSimulado, dir_bot: Path,
                                                             libro: Any) -> None:
    """Riesgo 11: lo que el vigilante envió y DAS aún no devolvió cuenta como puesto (`Foto.pendientes`): no se repite
    en cada pasada; si en `PENDIENTE_CADUCA_S` no aparece, caduca (se anota) y se repone con tokens NUEVOS."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    grabador = ClienteGrabador()
    m = montar(accion=lambda: grabador)
    m.listo()
    m.bombear(lambda: len(grabador.lineas) >= 2, "primer par")
    m.pasadas(4)
    assert len(neworders(grabador.lineas)) == 2 and len(m.v.pendientes) == 2
    reloj.avanzar(vg.PENDIENTE_CADUCA_S + 0.1)
    m.pasadas(1)
    assert len(de_tipo(m.regs(), "pendiente_caducado")) == 2
    tokens = [int(linea.split()[1]) for linea in neworders(grabador.lineas)]
    assert len(tokens) == 4 and len(set(tokens)) == 4           # un token nunca se reutiliza


def test_riesgo_11_un_cancel_sin_eco_no_se_repite_y_la_emergencia_duplicada_cae(montar, reloj: RelojSimulado,
                                                                                dir_bot: Path, libro: Any,
                                                                                simulador: Any) -> None:
    """R-C-07 plan B: dos emergencias sobre la misma posición ⇒ se cancela la MÁS NUEVA (una vez; el CANCEL pendiente
    cuenta como hecho hasta que caduca) y nada más."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    _sembrar_orden(simulador, f"NEWORDER {tok(2)} B {TICKER} STOP 100 STOPLMTP 4 4.12 TIF=DAY+")
    _sembrar_orden(simulador, f"NEWORDER {tok(3)} B {TICKER} STOP 100 STOPLMTP 4.52 6.52 TIF=DAY+")
    nueva = _sembrar_orden(simulador, f"NEWORDER {tok(4)} B {TICKER} STOP 100 STOPLMTP 4.52 6.52 TIF=DAY+")
    grabador = ClienteGrabador()
    m = montar(accion=lambda: grabador)
    m.listo()
    m.bombear(lambda: grabador.lineas, "cancelación de la sobrante")
    m.pasadas(4)
    assert grabador.lineas == [f"CANCEL {nueva}"]
    intencion = de_tipo(m.regs(), "cancel_intencion")
    assert len(intencion) == 1 and intencion[0].datos["id_das"] == nueva and intencion[0].datos["token"] == tok(4)
    reloj.avanzar(vg.PENDIENTE_CADUCA_S + 0.1)
    m.pasadas(1)
    assert grabador.lineas == [f"CANCEL {nueva}"] * 2               # DAS no la canceló: se repite tras caducar


def test_r_c_07_con_menos_posicion_reduce_los_stops_por_replace(montar, reloj: RelojSimulado, dir_bot: Path,
                                                                libro: Any, simulador: Any) -> None:
    """R-C-07: la posición bajó a 60 (TP parcial) y el ejecutor está caído ⇒ el vigilante REDUCE principal y emergencia
    a 60 con REPLACE (nunca un stop mayor que la posición) y no lo repite."""
    libro.sembrar_posicion(TICKER, -60, D("3.45"))
    escribir_diario_ejecutor(dir_bot, reloj)
    principal = _sembrar_orden(simulador, f"NEWORDER {tok(2)} B {TICKER} STOP 100 STOPLMTP 4 4.12 TIF=DAY+")
    emergencia = _sembrar_orden(simulador, f"NEWORDER {tok(3)} B {TICKER} STOP 100 STOPLMTP 4.52 6.52 TIF=DAY+")
    m = montar()
    m.listo()
    m.bombear(lambda: {o["lvqty"] for o in stops_vivos(libro)} == {60}, "stops reducidos a 60")
    m.pasadas(4)
    replaces = [linea for linea in m.recibidas() if linea.startswith("REPLACE")]
    assert sorted(replaces) == sorted([f"REPLACE {principal} 60 STOPLMT 4 4.12", f"REPLACE {emergencia} 60 STOPLMT 4.52 6.52"])
    assert neworders(m.recibidas()) == []
    assert len(de_tipo(m.regs(), "replace_intencion")) == 2
    assert simulador.errores() == []
