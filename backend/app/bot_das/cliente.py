"""Socket TCP con DAS: hilo lector, hilo emisor con cuotas y versión de serie, reconexión y candados de la sombra.

QUÉ HACE. `ClienteDAS` abre UNA conexión con el CMD API de DAS (normal o
watch), manda el LOGIN y arranca dos hilos vigilados: `das-lector` (bytes →
líneas → `protocolo.Parser` → `al_mensaje`, que solo encola) y `das-emisor`
(cola de salida con tope → descarte de versiones viejas por serie → espera de
cuota → `sendall`). `CuotaComandos` autolimita cada tipo de comando al 90 % de
lo que admite DAS (manual L1996-2016) con ventanas deslizantes sobre un reloj
inyectado; `PlanReconexion` da las esperas 2/4/8/16 y luego 30 s sin parar
(R-J-02). `ClienteSombra` es la fase sombra (R-O-03): las lecturas van al
DAS real y los comandos mutantes a un `Emparejador` interno que devuelve
mensajes SIMULADOS.

POR QUÉ ESTÁ AQUÍ. Es la única pieza con socket hacia DAS; `protocolo.py` es
puro y el `Decisor` nunca ve bytes. Aquí viven los dos candados de código de
la sombra: `EnvioProhibido` (un cliente `solo_lectura` no encola NINGÚN
mutante) y `desde_env`, que no construye un cliente con permiso para mandar
órdenes sin `BOT_DAS_PERMITIR_ORDENES=1` en el entorno (corrección 15: la
fase del fichero del cuadro no basta para pasar a dinero).

LAS TRAMPAS.
  * El principal NUNCA se bloquea en `enviar` (§3.2): encola y vuelve. Con
    la cola llena se descarta la línea más vieja de la MISMA serie y de
    versión ANTERIOR (A-04: solo lo que una versión posterior hace inútil;
    nunca un stop hermano de la misma versión); si no hay ninguna se espera
    50 ms una sola vez y, si sigue llena, se descarta la NUEVA con aviso y
    `enviar` devuelve False (G2-05): el `plan()` idempotente y el barrido
    la repondrán (riesgo 17).
  * Un `REPLACE` de stops con la cantidad ANTERIOR no puede salir después
    del fill (riesgo 7, injerto §8.6): `invalidar(serie, version)` purga la
    cola y el emisor vuelve a comprobarlo justo antes de mandar la línea.
  * Nada se purga en silencio (D2a-06): cada NEWORDER que ya estaba ENCOLADO
    y no llega a salir (versión vieja, cola llena, sesión caída) se comunica
    con `al_descartar(OrdenDescartada(token, serie, version, motivo,
    ticker))`, que SOLO encola (el ejecutor lo conecta a su cola de entrada y
    el decisor pasa la orden a CLOSED y relanza el plan). Lo que se descarta
    en el acto dentro de `enviar` se comunica con el valor de retorno
    (False) y NO por `al_descartar`: así un plan que se relanza con la cola
    llena o sin conexión no entra en bucle.
  * El emisor NO se bloquea en cabeza (A-01 / SEG-01): si la primera línea
    espera su cuota, sale la primera de detrás cuya cuota SÍ cabe y que no
    tenga delante, aún pendiente, otra línea con la que deba guardar el
    orden: misma `serie`, misma orden (`id_das` de CANCEL/REPLACE), mismo
    ticker en NEWORDER/CANCEL/REPLACE (el ticker de un id lo aprende el
    lector de los `%ORDER`/`%OrderAct`), mismo ticker o id de locate, y un
    `CANCEL ALL` que ningún mutante adelanta ni él adelanta a ninguno.
    Nada se reordena DENTRO de una categoría de cuota (esperan todas igual).
  * Lo encolado pertenece a UNA sesión. Si el socket cae, la cola se vacía
    y se avisa; `enviar` sin conexión descarta y avisa (el primer descarte
    de cada caída). Así nada viejo sale al reconectar ANTES de la
    reconciliación completa (R-J-02.5, F12).
  * DAS no confirma el LOGIN con un «ok» documentado (§1): `conectar` es
    True si el socket abrió y el LOGIN salió; `logon` se rellena después con
    las líneas `#OrderServer/#QuoteServer` (§5.26).
  * `al_estado(True, …)` se llama ANTES de arrancar el lector: en la cola
    del ejecutor el «conectado» va siempre delante de la primera línea del
    volcado. `al_estado(False, …)` solo en una caída real, una vez por
    sesión; `cerrar()` no lo llama (apagar no es una alarma).
  * Una línea con un salto de línea DENTRO serían dos comandos para DAS
    (riesgo 10): el candado de la sombra se consulta primero (lanza
    `EnvioProhibido` si cualquiera de los trozos es mutante) y después la
    línea se rechaza con `ValueError`.
  * El `sendall` y el `QUIT` de `cerrar()` comparten un cerrojo: dos hilos
    escribiendo a la vez intercalarían bytes de dos comandos.
  * Nada se registra sin pasar por `protocolo.redactar` (R-Q-01, riesgo 20):
    la clave del LOGIN va en claro en el socket y en NINGÚN otro sitio.
  * `CuotaComandos` usa el reloj inyectado (`mono()`); el emisor espera en
    tiempo real a pasos de 50 ms y vuelve a preguntar, así que con un
    `RelojSimulado` la cola avanza cuando el test mueve el reloj.
  * Un buffer sin `\\n` no puede crecer sin límite: pasado `TOPE_LINEA_BYTES`
    se entrega tal cual (saldrá `MsgDesconocido`) y se empieza de cero.
"""
from __future__ import annotations

import logging
import math
import os
import socket
import threading
from collections import deque
from typing import TYPE_CHECKING, Any, Callable, Optional

from app.bot_das.cerrojo import HiloVigilado
from app.bot_das.protocolo import (
    CODIFICACION,
    FIN_LINEA,
    Parser,
    cmd_login,
    cmd_quit,
    es_mutante,
    redactar,
)
from app.bot_das.tipos import (
    COLA_SALIDA_TOPE,
    DAS_RECONEXION_S,
    DAS_RECONEXION_TOPE_S,
    LOCATES_INQUIRE_S,
    MensajeDAS,
    MsgConexion,
    MsgOrden,
    MsgOrderAct,
    OrdenDescartada,
)
from app.bot_das.tokens import es_nuestro as _token_es_nuestro

if TYPE_CHECKING:                                   # solo para el tipado: importar cliente no carga el simulador
    from app.bot_das.simulador_das import Emparejador

logger = logging.getLogger(__name__)

# ── constantes del socket (§3.2) ──────────────────────────────────────
TAM_RECV = 4096                     # recv(4096)
TIMEOUT_RECV_S = 1.0                # el lector despierta cada segundo para mirar si debe parar
TOPE_LINEA_BYTES = 1 << 20          # 1 MiB sin '\n' → se entrega tal cual (riesgo 17: memoria acotada)
ESPERA_COLA_LLENA_S = 0.05          # §3.2: «se espera 50 ms y se reintenta una vez»
PASO_ESPERA_S = 0.05                # el emisor re-pregunta a la cuota como mucho cada 50 ms
TOLERANCIA_CUOTA_S = 1e-6           # sumas de float (0,02 × 49 + 0,02 ≠ 1,0): una marca que caduca «ahora» ya caducó
ESPERA_UNION_S = 2.0                # plazo para unir los hilos al cerrar
SERVIDORES_LOGON = ("OrderServer", "QuoteServer")
TOPE_IDS_CONOCIDOS = 50_000         # id_das → ticker que aprende el lector (A-01); memoria acotada, se olvida lo más viejo

# ── motivos de OrdenDescartada (D2a-06): el decisor los anota tal cual ──
MOTIVO_VERSION = "descartada por versión"
MOTIVO_COLA_LLENA = "descartada por versión (cola de salida llena)"
MOTIVO_SESION = "descartada: la conexión con DAS terminó antes de enviarla"

# ── variables de entorno (leídas en la llamada, nunca al importar) ────
ENV_HOST = "DAS_API_HOST"
ENV_PUERTO = "DAS_API_PORT"
ENV_USUARIO = "DAS_USUARIO"
ENV_CLAVE = "DAS_CLAVE"
ENV_CUENTA = "DAS_CUENTA"
ENV_PERMITIR_ORDENES = "BOT_DAS_PERMITIR_ORDENES"
HOST_POR_DEFECTO = "127.0.0.1"


class EnvioProhibido(RuntimeError):
    """R-O-03: un cliente de solo lectura (fase sombra) no envía NINGÚN comando mutante. Primer candado."""


# ══════════════════════════════════════════════════════════════════════
# Cuotas (manual L1996-2016; §5.29; riesgos 11 y 36)
# ══════════════════════════════════════════════════════════════════════
class CuotaComandos:
    """Ventanas deslizantes por tipo de comando, al `margen` (90 %) de lo que admite DAS. PURA: reloj inyectado.

    Límites del manual (L1996-2016): NEWORDER 50/s, CANCEL 100/min, REPLACE
    100/min, SLNEWORDER 100/min y SLPRICEINQUIRE 1 cada 3 s. Con margen 0,9:
    45 órdenes por segundo, 90 CANCEL/REPLACE/SLNEWORDER por minuto y una
    consulta de locate cada 3,33 s. El resto de comandos (GET, SB, …) no tiene
    cuota documentada y no espera. La cuota del SLPRICEINQUIRE es GLOBAL (la
    lectura conservadora de la pregunta 7 del §14, riesgo 36).
    """

    def __init__(self, reloj, ordenes_s: int = 50, cancel_min: int = 100, replace_min: int = 100,
                 locate_min: int = 100, inquire_s: float = LOCATES_INQUIRE_S, margen: float = 0.9) -> None:
        if not callable(getattr(reloj, "mono", None)):
            raise TypeError(f"reloj debe tener mono(): {reloj!r}")
        for nombre, valor in (("ordenes_s", ordenes_s), ("cancel_min", cancel_min),
                              ("replace_min", replace_min), ("locate_min", locate_min)):
            if type(valor) is not int or valor < 1:
                raise ValueError(f"{nombre} debe ser un entero ≥ 1: {valor!r}")
        if isinstance(inquire_s, bool) or not isinstance(inquire_s, (int, float)) \
                or not math.isfinite(inquire_s) or inquire_s <= 0:
            raise ValueError(f"inquire_s debe ser un número finito > 0: {inquire_s!r}")
        if isinstance(margen, bool) or not isinstance(margen, (int, float)) \
                or not math.isfinite(margen) or not (0 < margen <= 1):
            raise ValueError(f"margen debe estar en (0, 1]: {margen!r}")
        self._reloj = reloj
        self._margen = float(margen)
        # categoría → (ventana en s, cuántos caben en la ventana)
        self._limites: dict[str, tuple[float, int]] = {
            "NEWORDER": (1.0, self._cabida(ordenes_s)),
            "CANCEL": (60.0, self._cabida(cancel_min)),
            "REPLACE": (60.0, self._cabida(replace_min)),
            "SLNEWORDER": (60.0, self._cabida(locate_min)),
            "SLPRICEINQUIRE": (float(inquire_s) / self._margen, 1),   # 1 cada 3 s al 90 % = 1 cada 3,33 s
        }
        self._marcas: dict[str, deque[float]] = {clave: deque() for clave in self._limites}

    @property
    def limites(self) -> dict[str, tuple[float, int]]:
        """Copia de {comando: (ventana_s, cabida)} ya con el margen aplicado."""
        return dict(self._limites)

    def espera_para(self, linea: str) -> float:
        """Segundos a esperar antes de mandar `linea` (0.0 si cabe ya). Manual L1996-2016 al margen (riesgo 11).

        La espera es exacta: lo que falta para que caduque la marca que deja
        sitio en la ventana deslizante. Un comando sin cuota devuelve 0.0.
        """
        categoria = self._categoria(linea)
        if categoria is None:
            return 0.0
        ahora = float(self._reloj.mono())
        ventana, cabida = self._limites[categoria]
        marcas = self._purgar(categoria, ahora)
        if len(marcas) < cabida:
            return 0.0
        libera = marcas[len(marcas) - cabida] + ventana     # la marca cuya caducidad deja un hueco
        espera = libera - ahora
        return espera if espera > TOLERANCIA_CUOTA_S else 0.0

    def anotar(self, linea: str) -> None:
        """Registra que `linea` acaba de salir (lo llama el emisor DESPUÉS del `sendall`)."""
        categoria = self._categoria(linea)
        if categoria is None:
            return
        ahora = float(self._reloj.mono())
        self._purgar(categoria, ahora).append(ahora)

    # ── privados ──────────────────────────────────────────────────────
    def _cabida(self, limite: int) -> int:
        # +1e-9: 100·0,9 en coma flotante puede quedarse en 89,99999…; el margen nunca puede dejar 0
        return max(1, math.floor(limite * self._margen + 1e-9))

    def _categoria(self, linea: str) -> Optional[str]:
        if not isinstance(linea, str):
            raise TypeError(f"la cuota espera una línea de texto, no {type(linea).__name__}")
        partes = linea.split(None, 1)
        if not partes:
            return None
        clave = partes[0].upper()
        return clave if clave in self._limites else None

    def _purgar(self, categoria: str, ahora: float) -> deque[float]:
        ventana, _cabida = self._limites[categoria]
        marcas = self._marcas[categoria]
        while marcas and marcas[0] <= ahora - ventana + TOLERANCIA_CUOTA_S:
            marcas.popleft()
        return marcas


# ══════════════════════════════════════════════════════════════════════
# Reconexión (R-J-02 (2))
# ══════════════════════════════════════════════════════════════════════
class PlanReconexion:
    """Esperas entre intentos de reconexión: 2, 4, 8, 16 y después 30 s sin parar (R-J-02). PURO.

    Lo usa el ejecutor para programar «das_reconectar»; `reiniciar()` tras
    una conexión buena vuelve a empezar por 2 s.
    """

    def __init__(self, esperas: tuple[float, ...] = DAS_RECONEXION_S, tope: float = DAS_RECONEXION_TOPE_S) -> None:
        esperas = tuple(esperas)
        if not esperas:
            raise ValueError("esperas no puede estar vacía")
        for x in esperas + (tope,):
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0:
                raise ValueError(f"cada espera debe ser un número finito > 0: {x!r}")
        self._esperas = tuple(float(x) for x in esperas)
        self._tope = float(tope)
        self._intentos = 0

    def siguiente(self) -> float:
        """Espera antes del próximo intento y cuenta el intento (2, 4, 8, 16, 30, 30, …)."""
        espera = self._esperas[self._intentos] if self._intentos < len(self._esperas) else self._tope
        self._intentos += 1
        return espera

    def reiniciar(self) -> None:
        """Tras reconectar: el siguiente corte vuelve a empezar por la primera espera."""
        self._intentos = 0

    @property
    def intentos(self) -> int:
        return self._intentos


# ══════════════════════════════════════════════════════════════════════
# Cliente
# ══════════════════════════════════════════════════════════════════════
class _Linea:
    """Una línea en la cola de salida. Objeto propio: el emisor compara por IDENTIDAD al sacarla.

    `claves`, `barrera` y `mutante` deciden qué líneas de detrás pueden
    adelantarla cuando espera su cuota (A-01); `token` y `ticker` (solo
    NEWORDER) sirven para avisar al decisor si se purga sin salir (D2a-06).
    """

    __slots__ = ("texto", "serie", "version", "categoria", "claves", "barrera", "mutante", "token", "ticker")

    def __init__(self, texto: str, serie: Optional[str], version: int, claves: frozenset[str] = frozenset(),
                 barrera: bool = False, mutante: bool = False, token: Optional[int] = None,
                 ticker: Optional[str] = None) -> None:
        self.texto = texto
        self.serie = serie
        self.version = version
        partes = texto.split(None, 1)
        self.categoria = partes[0].upper() if partes else ""
        self.claves = claves
        self.barrera = barrera
        self.mutante = mutante
        self.token = token
        self.ticker = ticker


class _Sesion:
    """Un socket abierto con su buffer de lectura, su parser y sus dos hilos."""

    def __init__(self, numero: int, sock: socket.socket, parser: Parser) -> None:
        self.numero = numero
        self.sock = sock
        self.parser = parser
        self.buffer = bytearray()
        self.viva = True
        self.fin = threading.Event()
        self.lector: Optional[HiloVigilado] = None
        self.emisor: Optional[HiloVigilado] = None


class ClienteDAS:
    """Una conexión con el CMD API de DAS: LOGIN, hilo lector, hilo emisor con cuotas y candado de sombra (§3.2).

    `al_mensaje(msg)` y `al_estado(conectado, motivo)` se llaman desde los
    hilos del cliente y deben SOLO encolar. `al_aviso(texto)` (opcional)
    recibe los avisos de nivel 2 (cola llena, líneas descartadas sin
    conexión); `al_caida_hilo(nombre, error, relanzado)` (opcional) recibe las
    caídas de los `HiloVigilado` (el ejecutor las convierte en `HiloCaido`).
    `parser` opcional: si no se da, cada sesión estrena un `Parser` con
    `es_nuestro` = token del esquema y del día de `reloj.hoy()`.
    `al_descartar(OrdenDescartada)` (opcional, D2a-06): cada NEWORDER que
    estaba encolado y se purga sin salir (versión vieja, cola llena, sesión
    caída). Se llama desde el hilo que purga (emisor, lector o el que llama
    a `enviar`/`invalidar`) y debe SOLO encolar; el ejecutor le pasa el
    `poner` de su cola de entrada. Se eligió un callback propio (y no
    `al_mensaje`) porque `al_mensaje` es de `MensajeDAS` (lo que dice DAS) y
    `OrdenDescartada` es un `Mensaje` de la cola del ejecutor (lo que dice
    el propio bot).
    """

    def __init__(self, host: str, puerto: int, usuario: str, clave: str, cuenta: str, watch: bool,
                 solo_lectura: bool, al_mensaje: Callable[[MensajeDAS], None], al_estado: Callable[[bool, str], None],
                 reloj, cuota: Optional[CuotaComandos] = None, timeout_s: float = 5.0,
                 parser: Optional[Parser] = None, al_aviso: Optional[Callable[[str], None]] = None,
                 al_caida_hilo: Optional[Callable[[str, str, bool], None]] = None,
                 tope_cola: int = COLA_SALIDA_TOPE,
                 al_descartar: Optional[Callable[[OrdenDescartada], None]] = None) -> None:
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host debe ser un texto no vacío")
        if type(puerto) is not int or not (1 <= puerto <= 65535):
            raise ValueError(f"puerto inválido: {puerto!r}")
        for nombre, valor in (("usuario", usuario), ("clave", clave), ("cuenta", cuenta)):
            # el mensaje NUNCA lleva el valor (R-Q-01): protocolo._palabra lo mostraría con repr
            if not isinstance(valor, str) or not valor or any(ch.isspace() for ch in valor):
                raise ValueError(f"{nombre} de DAS inválido: debe ser una sola palabra sin espacios")
        if not callable(al_mensaje) or not callable(al_estado):
            raise TypeError("al_mensaje y al_estado deben ser funciones")
        if al_aviso is not None and not callable(al_aviso):
            raise TypeError("al_aviso debe ser una función texto -> None")
        if al_caida_hilo is not None and not callable(al_caida_hilo):
            raise TypeError("al_caida_hilo debe ser una función (nombre, error, relanzado) -> None")
        if al_descartar is not None and not callable(al_descartar):
            raise TypeError("al_descartar debe ser una función OrdenDescartada -> None")
        if not callable(getattr(reloj, "mono", None)) or not callable(getattr(reloj, "hoy", None)):
            raise TypeError(f"reloj debe tener mono() y hoy(): {reloj!r}")
        if cuota is not None and not (callable(getattr(cuota, "espera_para", None))
                                      and callable(getattr(cuota, "anotar", None))):
            raise TypeError("cuota debe tener espera_para(linea) y anotar(linea)")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) \
                or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError(f"timeout_s debe ser un número finito > 0: {timeout_s!r}")
        if type(tope_cola) is not int or tope_cola < 1:
            raise ValueError(f"tope_cola debe ser un entero ≥ 1: {tope_cola!r}")
        if parser is not None and not isinstance(parser, Parser):
            raise TypeError("parser debe ser un protocolo.Parser")
        self._host = host.strip()
        self._puerto = puerto
        self._usuario = usuario
        self._clave = clave
        self._cuenta = cuenta
        self._watch = bool(watch)
        self._solo_lectura = bool(solo_lectura)
        self._al_mensaje = al_mensaje
        self._al_estado = al_estado
        self._al_aviso = al_aviso
        self._al_caida_hilo = al_caida_hilo
        self._al_descartar = al_descartar
        self._reloj = reloj
        self._cuota = cuota if cuota is not None else CuotaComandos(reloj)
        self._timeout_s = float(timeout_s)
        self._parser_fijo = parser
        self._es_nuestro: Callable[[int], bool] = (
            parser.es_nuestro if parser is not None else (lambda token: _token_es_nuestro(token, reloj.hoy())))
        self._tope_cola = tope_cola
        # estado compartido entre hilos: se toca siempre con `_cond` tomado
        self._cond = threading.Condition(threading.Lock())
        self._cola: deque[_Linea] = deque()
        self._vigentes: dict[str, int] = {}
        self._ticker_de_id: dict[int, str] = {}             # id_das → ticker (A-01), lo aprende el lector
        self._sesion: Optional[_Sesion] = None
        self._numero = 0
        self._logon: dict[str, Optional[bool]] = {s: None for s in SERVIDORES_LOGON}
        self._ultimo_recibido_en: Optional[float] = None
        self._descartadas = 0
        self._sin_conexion = 0
        self._cerrojo_envio = threading.Lock()              # sendall del emisor y QUIT de cerrar() no se intercalan
        self._cerrojo_ciclo = threading.Lock()              # conectar/cerrar en serie

    # ── propiedades ───────────────────────────────────────────────────
    @property
    def conectado(self) -> bool:
        """True mientras el socket de la sesión actual está abierto."""
        with self._cond:
            return self._sesion is not None and self._sesion.viva

    @property
    def ultimo_recibido_en(self) -> Optional[float]:
        """`reloj.mono()` de los últimos bytes recibidos, o None si nunca llegó nada."""
        with self._cond:
            return self._ultimo_recibido_en

    @property
    def logon(self) -> dict[str, Optional[bool]]:
        """{"OrderServer": True/False/None, "QuoteServer": …} por las líneas `MsgConexion` de esta sesión (§5.26)."""
        with self._cond:
            return dict(self._logon)

    @property
    def hilos_vivos(self) -> bool:
        """Con conexión: los dos `HiloVigilado` (das-lector y das-emisor) están vivos. Sin conexión: True.

        Sin sesión no debe correr ningún hilo (la caída la gestiona el plan
        de reconexión, no el supervisor): así el latido del ejecutor solo se
        para por un hilo MUERTO, no por un DAS caído (injerto §8.11).
        """
        with self._cond:
            s = self._sesion
            if s is None or not s.viva:
                return True
        return bool(s.lector is not None and s.lector.vivo and s.emisor is not None and s.emisor.vivo)

    @property
    def pendientes(self) -> int:
        """Líneas en la cola de salida (para la foto, riesgo 17)."""
        with self._cond:
            return len(self._cola)

    @property
    def descartadas(self) -> int:
        """Líneas descartadas en total (cola llena, sin conexión o sesión caída; NO cuenta las obsoletas por serie).

        Las purgadas por versión vieja con la cola llena (A-04) sí cuentan: se
        tiraron para hacer sitio.
        """
        with self._cond:
            return self._descartadas

    @property
    def solo_lectura(self) -> bool:
        return self._solo_lectura

    @property
    def watch(self) -> bool:
        return self._watch

    @property
    def cuenta(self) -> str:
        return self._cuenta

    @property
    def es_nuestro(self) -> Callable[[int], bool]:
        """La función token → bool con la que se parsean los mensajes (la usa `ClienteSombra`)."""
        return self._es_nuestro

    # ── ciclo de vida ─────────────────────────────────────────────────
    def conectar(self) -> bool:
        """Abre el socket, manda el LOGIN y arranca `das-emisor` y `das-lector`. NUNCA lanza (R-J-02).

        True si el socket abrió y el LOGIN salió (no hay «login OK»
        documentado, §1; el resultado real llega en `logon`). False si no se
        pudo: no llama a `al_estado` (no hubo transición) y el ejecutor
        reprograma con `PlanReconexion`. Si ya está conectado devuelve True
        sin hacer nada.
        """
        with self._cerrojo_ciclo:
            with self._cond:
                anterior = self._sesion
                if anterior is not None and anterior.viva:
                    return True
            if anterior is not None:
                self._unir(anterior)
            login = cmd_login(self._usuario, self._clave, self._cuenta, self._watch)
            try:
                sock = socket.create_connection((self._host, self._puerto), timeout=self._timeout_s)
            except OSError as exc:  # frontera de red (R-J-02): no se pudo conectar; se reintenta por plan
                logger.warning("DAS %s:%s no acepta la conexión: %s", self._host, self._puerto,
                               redactar(f"{type(exc).__name__}: {exc}"))
                return False
            try:
                sock.settimeout(TIMEOUT_RECV_S)
                sock.sendall((login + FIN_LINEA).encode(CODIFICACION))
            except OSError as exc:  # frontera de red (R-J-02): el LOGIN no salió; socket fuera
                logger.warning("DAS %s:%s: el LOGIN no salió: %s", self._host, self._puerto,
                               redactar(f"{type(exc).__name__}: {exc}"))
                _cerrar_socket(sock)
                return False
            logger.info("conectado a DAS %s:%s (%s): %s", self._host, self._puerto,
                        "watch" if self._watch else "normal", redactar(login))
            parser = self._parser_fijo or Parser(self._es_nuestro, watch=self._watch, cuenta=self._cuenta)
            with self._cond:
                self._numero += 1
                s = _Sesion(self._numero, sock, parser)
                perdidas = list(self._cola)
                viejas = len(perdidas)
                self._cola.clear()                          # nada de otra sesión sale en esta (R-J-02.5)
                self._descartadas += viejas
                self._sesion = s
                self._logon = {srv: None for srv in SERVIDORES_LOGON}
                self._sin_conexion = 0
            if viejas:
                logger.warning("descartadas %d líneas de una sesión anterior", viejas)
                self._reportar_descartes(perdidas, MOTIVO_SESION)
            s.emisor = HiloVigilado("das-emisor", lambda: self._cuerpo_emisor(s), self._caida_hilo)
            s.lector = HiloVigilado("das-lector", lambda: self._cuerpo_lector(s), self._caida_hilo)
            s.emisor.arrancar()
            self._llamar_estado(True, f"conectado a {self._host}:{self._puerto}")   # ANTES del lector: va delante del volcado
            s.lector.arrancar()
            return True

    def cerrar(self) -> None:
        """Manda QUIT si se puede, cierra el socket y para los hilos. NUNCA lanza; no llama a `al_estado`.

        Lo pendiente en la cola se descarta (apagado ordenado: el ejecutor
        ya no tiene nada que mandar). Idempotente.
        """
        with self._cerrojo_ciclo:
            with self._cond:
                s = self._sesion
            if s is None:
                return
            if s.viva:
                try:
                    with self._cerrojo_envio:
                        s.sock.sendall((cmd_quit() + FIN_LINEA).encode(CODIFICACION))
                except OSError as exc:  # frontera de red: el QUIT es cortesía; el socket se cierra igual
                    logger.info("QUIT no salió: %s", redactar(f"{type(exc).__name__}: {exc}"))
            self._caida(s, "cerrado por el bot", avisar=False)
            self._unir(s)

    # ── envío ─────────────────────────────────────────────────────────
    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> bool:
        """Encola `linea` para el emisor. NO bloquea (salvo 50 ms con la cola llena). R-O-03, riesgos 7, 10 y 17.

        Orden de comprobaciones: (1) `TypeError` si no es texto; (2)
        `EnvioProhibido` si el cliente es de solo lectura y la línea es
        mutante (`protocolo.es_mutante`), ANTES de tocar la cola; (3)
        `ValueError` si la línea está vacía, lleva saltos dentro o no cabe en
        latin-1, o si `serie`/`version` no son válidas. Sin conexión la línea
        se descarta y se avisa (el primer descarte de cada caída).

        Devuelve True si la línea quedó ENCOLADA y False si se descartó en el
        acto (sin conexión o cola llena): G2-05, el ejecutor no debe anotar
        `orden_enviada` de una línea que no salió. Encolada no es enviada: si
        después se purga sin salir, llega `al_descartar` (D2a-06).
        """
        if not isinstance(linea, str):
            raise TypeError(f"enviar espera una línea de texto, no {type(linea).__name__}")
        if self._solo_lectura and es_mutante(linea):
            logger.warning("EnvioProhibido (solo lectura, R-O-03): %s", redactar(linea))
            raise EnvioProhibido(f"cliente de solo lectura: comando mutante prohibido: {redactar(linea)}")
        self._validar_linea(linea)
        if serie is not None and (not isinstance(serie, str) or not serie.strip()):
            raise ValueError(f"serie debe ser un texto no vacío o None: {serie!r}")
        if type(version) is not int:
            raise ValueError(f"version debe ser un entero: {version!r}")
        avisos: list[str] = []
        purgadas: list[_Linea] = []
        encolada = False
        with self._cond:
            item = self._linea_nueva(linea, serie, version)
            sesion = self._sesion
            if sesion is not None and sesion.viva and len(self._cola) >= self._tope_cola and serie is not None:
                # A-04: solo lo que una versión POSTERIOR hace inútil; un stop hermano de la misma versión no
                vieja = next((x for x in self._cola if x.serie == serie and x.version < version), None)
                if vieja is not None:
                    self._cola.remove(vieja)
                    self._descartadas += 1
                    purgadas.append(vieja)
                    avisos.append(f"cola de salida llena ({self._tope_cola}): descartada la línea más vieja "
                                  f"de la serie {serie} (v{vieja.version} < v{version}): {redactar(vieja.texto)}")
            if sesion is not None and sesion.viva and len(self._cola) >= self._tope_cola:
                self._cond.wait(ESPERA_COLA_LLENA_S)        # §3.2: 50 ms y un solo reintento
            if sesion is None or not sesion.viva or self._sesion is not sesion:
                self._descartadas += 1
                self._sin_conexion += 1
                if self._sin_conexion == 1:
                    avisos.append(f"DAS sin conexión: se descartan las líneas a enviar (primera: {redactar(linea)})")
                logger.warning("sin conexión con DAS, descartada: %s", redactar(linea))
            elif len(self._cola) >= self._tope_cola:
                self._descartadas += 1
                avisos.append(f"cola de salida llena ({self._tope_cola}): descartada la línea nueva: "
                              f"{redactar(linea)}")
            else:
                self._cola.append(item)
                self._cond.notify_all()
                encolada = True
        self._reportar_descartes(purgadas, MOTIVO_COLA_LLENA)
        for texto in avisos:
            self._avisar(texto)
        return encolada

    def invalidar(self, serie: str, version: int) -> None:
        """Injerto A §8.6 (riesgo 7): las líneas de `serie` con versión < `version` no salen (ni las ya encoladas).

        La versión vigente de cada serie solo sube. El emisor lo vuelve a
        comprobar justo antes del `sendall`. Cada NEWORDER purgado se
        comunica con `al_descartar` (D2a-06): nada se purga en silencio.
        """
        if not isinstance(serie, str) or not serie.strip():
            raise ValueError(f"serie debe ser un texto no vacío: {serie!r}")
        if type(version) is not int:
            raise ValueError(f"version debe ser un entero: {version!r}")
        with self._cond:
            if version > self._vigentes.get(serie, version - 1):
                self._vigentes[serie] = version
            fuera = [x for x in self._cola if self._obsoleta(x)]
            for x in fuera:
                self._cola.remove(x)
            if fuera:
                self._cond.notify_all()
        self._reportar_descartes(fuera, MOTIVO_VERSION)

    # ── construcción desde el entorno (corrección 15) ─────────────────
    @staticmethod
    def desde_env(watch: bool, solo_lectura: bool, **kw: Any) -> "ClienteDAS":
        """Construye el cliente con DAS_API_HOST (127.0.0.1), DAS_API_PORT, DAS_USUARIO, DAS_CLAVE y DAS_CUENTA.

        SEGUNDO CANDADO (corrección 15, R-O-03): con `solo_lectura=False`
        exige `BOT_DAS_PERMITIR_ORDENES=1` en el entorno; sin él lanza
        `RuntimeError`. Las variables se leen AHORA (nunca al importar). Los
        mensajes de error nombran la variable, jamás su valor. `kw` pasa tal
        cual al constructor (`al_mensaje`, `al_estado`, `reloj`, …).
        """
        if not solo_lectura and os.environ.get(ENV_PERMITIR_ORDENES, "").strip() != "1":
            raise RuntimeError(
                f"{ENV_PERMITIR_ORDENES}=1 es obligatorio en el entorno (.env del VPS) para un cliente que envía "
                f"órdenes (corrección 15, R-O-03): la fase del fichero del cuadro no basta para operar con dinero")
        host = os.environ.get(ENV_HOST, "").strip() or HOST_POR_DEFECTO
        puerto_txt = os.environ.get(ENV_PUERTO, "").strip()
        if not puerto_txt:
            raise RuntimeError(f"{ENV_PUERTO} no está en el entorno: es obligatorio (Menu->Setup->Other "
                               f"Configuration de DAS, manual L2023-2024)")
        if not puerto_txt.isdigit() or not (1 <= int(puerto_txt) <= 65535):
            raise RuntimeError(f"{ENV_PUERTO} no es un puerto válido (1-65535)")
        faltan = [n for n in (ENV_USUARIO, ENV_CLAVE, ENV_CUENTA) if not os.environ.get(n, "").strip()]
        if faltan:
            raise RuntimeError(f"faltan en el entorno: {', '.join(faltan)} (obligatorias para el LOGIN de DAS)")
        try:
            return ClienteDAS(host, int(puerto_txt), os.environ[ENV_USUARIO].strip(), os.environ[ENV_CLAVE].strip(),
                              os.environ[ENV_CUENTA].strip(), watch, solo_lectura, **kw)
        except ValueError as exc:   # los mensajes del constructor nombran el campo, nunca su valor (R-Q-01)
            raise RuntimeError(f"configuración del cliente DAS no válida: {exc}") from exc

    # ── hilos ─────────────────────────────────────────────────────────
    def _cuerpo_lector(self, s: _Sesion) -> None:
        """das-lector: recv(4096) con timeout 1 s → líneas por '\\n' sin '\\r' → latin-1 → parser → al_mensaje (§3.2)."""
        while not s.fin.is_set():
            try:
                datos = s.sock.recv(TAM_RECV)
            except socket.timeout:
                continue
            except OSError as exc:  # frontera de red (R-J-02): socket roto → caída
                self._caida(s, f"error de lectura: {type(exc).__name__}: {exc}")
                return
            if not datos:
                self._caida(s, "DAS cerró la conexión (EOF)")
                return
            with self._cond:
                if self._sesion is s:
                    self._ultimo_recibido_en = float(self._reloj.mono())
            s.buffer += datos                               # bytearray: añadir no copia lo acumulado
            while True:
                corte = s.buffer.find(b"\n")
                if corte < 0:
                    break
                cruda = bytes(s.buffer[:corte])
                del s.buffer[:corte + 1]
                self._entregar(s, cruda.rstrip(b"\r"))
            if len(s.buffer) > TOPE_LINEA_BYTES:
                cruda = bytes(s.buffer)
                s.buffer.clear()
                logger.warning("línea de DAS de más de %d bytes sin fin de línea: se entrega tal cual", TOPE_LINEA_BYTES)
                self._entregar(s, cruda.rstrip(b"\r"))

    def _entregar(self, s: _Sesion, cruda: bytes) -> None:
        msg = s.parser.parsear(cruda.decode(CODIFICACION, errors="replace"))   # parsear NUNCA lanza
        if isinstance(msg, (MsgOrden, MsgOrderAct)):
            self._aprender_ticker(msg.id, msg.ticker)
        if isinstance(msg, MsgConexion) and msg.servidor in SERVIDORES_LOGON:
            with self._cond:
                if self._sesion is s:
                    if msg.evento == "Logon:Successful":
                        self._logon[msg.servidor] = True
                    elif msg.evento in ("Logon:Failed", "Connect:Failed", "Missing heartbeat", "Lost Connection"):
                        self._logon[msg.servidor] = False
        try:
            self._al_mensaje(msg)
        except Exception as exc:  # noqa: BLE001 — frontera de callback: un al_mensaje que falla no deja sordo al lector (H-5)
            logger.error("al_mensaje falló con %s: %s", redactar(msg.cruda), redactar(f"{type(exc).__name__}: {exc}"))

    def _cuerpo_emisor(self, s: _Sesion) -> None:
        """das-emisor: descarta lo obsoleto por serie, elige la primera línea que cabe en su cuota, sendall y anota.

        §3.2 con A-01 / SEG-01: la cabeza que espera su cuota NO retiene lo de
        detrás; sale la primera línea cuya cuota cabe y que no deba guardar
        el orden con otra anterior aún pendiente (`_elegir`).
        """
        while not s.fin.is_set():
            with self._cond:
                if not s.viva:
                    return
                if not self._cola:
                    self._cond.wait(0.2)
                    continue
                obsoletas = [x for x in self._cola if self._obsoleta(x)]
                for x in obsoletas:
                    self._cola.remove(x)
                if obsoletas:
                    self._cond.notify_all()
                vistas = list(self._cola)
            if obsoletas:
                self._reportar_descartes(obsoletas, MOTIVO_VERSION)
            if not vistas:
                continue
            item, espera = self._elegir(vistas)
            if item is None:
                s.fin.wait(min(espera, PASO_ESPERA_S))
                continue
            with self._cond:
                if not s.viva:
                    return
                # delante de `item` solo pudo DESAPARECER algo (se encola al final): lo que se decidió sigue valiendo
                if self._obsoleta(item) or not any(x is item for x in self._cola):
                    continue                                # cambió mientras se miraba la cuota: se re-evalúa
                self._cola.remove(item)
                self._cond.notify_all()
            try:
                with self._cerrojo_envio:
                    s.sock.sendall((item.texto + FIN_LINEA).encode(CODIFICACION))
            except OSError as exc:  # frontera de red (R-J-02): socket roto al escribir → caída
                self._caida(s, f"error de escritura: {type(exc).__name__}: {exc}")
                return
            self._cuota.anotar(item.texto)
            logger.debug("→ DAS: %s", redactar(item.texto))

    # ── privados ──────────────────────────────────────────────────────
    def _caida(self, s: _Sesion, motivo: str, avisar: bool = True) -> None:
        """Fin de la sesión `s` (una sola vez): cola vaciada, socket cerrado y `al_estado(False)` si `avisar`."""
        with self._cond:
            if not s.viva:
                return
            s.viva = False
            s.fin.set()
            actual = self._sesion is s
            lineas_perdidas = list(self._cola) if actual else []
            perdidas = len(lineas_perdidas)
            if actual:
                self._cola.clear()
                self._descartadas += perdidas
                self._cond.notify_all()
        self._reportar_descartes(lineas_perdidas, MOTIVO_SESION)   # D2a-06: el decisor no las cree vivas
        _cerrar_socket(s.sock)
        if actual:
            logger.log(logging.WARNING if avisar else logging.INFO, "conexión con DAS terminada: %s", redactar(motivo))
        if perdidas:
            texto = f"conexión con DAS terminada: {perdidas} líneas pendientes descartadas"
            if avisar:
                self._avisar(texto)
            else:
                logger.warning(texto)
        if actual and avisar:
            self._llamar_estado(False, redactar(motivo))

    def _unir(self, s: _Sesion) -> None:
        for hilo in (s.lector, s.emisor):
            if hilo is not None:
                hilo.parar(ESPERA_UNION_S)

    def _obsoleta(self, item: _Linea) -> bool:
        """Con `_cond` tomado: la serie del item fue invalidada con una versión posterior (injerto §8.6)."""
        return item.serie is not None and item.serie in self._vigentes and item.version < self._vigentes[item.serie]

    def _linea_nueva(self, texto: str, serie: Optional[str], version: int) -> _Linea:
        """Con `_cond` tomado: la `_Linea` con sus claves de orden (A-01) y, si es NEWORDER, token y ticker (D2a-06).

        Claves: `serie:S`; `ticker:T` para NEWORDER, CANCEL ALLSYMB y los
        CANCEL/REPLACE cuyo id ya se vio en un `%ORDER`/`%OrderAct`; `id:N`
        para CANCEL/REPLACE por id; `locate:T` y `locate_id:N` para los SL*.
        `CANCEL ALL` es una barrera para todo mutante.
        """
        partes = texto.split()
        palabra = partes[0].upper()
        claves: set[str] = set()
        if serie is not None:
            claves.add("serie:" + serie)
        barrera = False
        token: Optional[int] = None
        ticker: Optional[str] = None
        if palabra == "NEWORDER" and len(partes) > 3:
            ticker = partes[3]
            claves.add("ticker:" + ticker.upper())
            token = _entero_o_none(partes[1])
        elif palabra in ("CANCEL", "REPLACE") and len(partes) > 1:
            arg = partes[1].upper()
            if palabra == "CANCEL" and arg == "ALL":
                barrera = True
            elif palabra == "CANCEL" and arg == "ALLSYMB" and len(partes) > 2:
                claves.add("ticker:" + partes[2].upper())
            else:
                id_das = _entero_o_none(partes[1])
                if id_das is not None:
                    claves.add(f"id:{id_das}")
                    conocido = self._ticker_de_id.get(id_das)
                    if conocido is not None:
                        claves.add("ticker:" + conocido)
        elif palabra in ("SLPRICEINQUIRE", "SLNEWORDER") and len(partes) > 1:
            claves.add("locate:" + partes[1].upper())
        elif palabra in ("SLOFFEROPERATION", "SLCANCELORDER") and len(partes) > 1:
            claves.add("locate_id:" + partes[1])
        return _Linea(texto, serie, version, frozenset(claves), barrera, es_mutante(texto), token, ticker)

    def _elegir(self, vistas: list[_Linea]) -> tuple[Optional[_Linea], float]:
        """A-01 / SEG-01: la primera línea que cabe en su cuota y no adelanta a otra con la que guarda el orden.

        Devuelve (línea, 0.0) o (None, espera mínima). Una línea no adelanta a
        otra anterior aún pendiente si comparten alguna clave (serie, orden,
        ticker, locate) o si una de las dos es `CANCEL ALL` y la otra es un
        mutante. La cuota se consulta una vez por categoría (la
        `CuotaComandos` clasifica por la primera palabra): dentro de una
        categoría nada se reordena.
        """
        claves_previas: set[str] = set()
        barrera_previa = False
        mutante_previo = False
        esperas: dict[str, float] = {}
        espera_min = math.inf
        for x in vistas:
            bloqueada = (bool(x.claves & claves_previas) or (barrera_previa and x.mutante)
                         or (x.barrera and mutante_previo))
            if not bloqueada:
                espera = esperas.get(x.categoria)
                if espera is None:
                    espera = float(self._cuota.espera_para(x.texto))
                    esperas[x.categoria] = espera
                if espera <= 0:
                    return x, 0.0
                espera_min = min(espera_min, espera)
            claves_previas |= x.claves
            barrera_previa = barrera_previa or x.barrera
            mutante_previo = mutante_previo or x.mutante
        return None, (espera_min if math.isfinite(espera_min) else PASO_ESPERA_S)

    def _aprender_ticker(self, id_das: int, ticker: str) -> None:
        """id_das → ticker de lo que dice DAS (A-01): así un CANCEL/REPLACE por id guarda el orden con su ticker."""
        if type(id_das) is not int or not isinstance(ticker, str) or not ticker:
            return
        with self._cond:
            if id_das not in self._ticker_de_id and len(self._ticker_de_id) >= TOPE_IDS_CONOCIDOS:
                self._ticker_de_id.pop(next(iter(self._ticker_de_id)))     # se olvida el más viejo
            self._ticker_de_id[id_das] = ticker.upper()

    def _reportar_descartes(self, lineas: list[_Linea], motivo: str) -> None:
        """D2a-06: registra cada línea purgada sin salir y avisa al decisor de cada NEWORDER. Sin `_cond` tomado."""
        for x in lineas:
            logger.info("%s (serie %s v%d): %s", motivo, x.serie, x.version, redactar(x.texto))
            if x.token is None or self._al_descartar is None:
                continue
            try:
                self._al_descartar(OrdenDescartada(token=x.token, serie=x.serie, version=x.version, motivo=motivo,
                                                   ticker=x.ticker))
            except Exception as exc:  # noqa: BLE001 — frontera de callback: un al_descartar que falla no para el emisor
                logger.error("al_descartar falló con %s: %s", redactar(x.texto),
                             redactar(f"{type(exc).__name__}: {exc}"))

    @staticmethod
    def _validar_linea(linea: str) -> None:
        if not linea.strip():
            raise ValueError("línea vacía")
        if linea.splitlines() != [linea]:
            raise ValueError(f"la línea lleva saltos de línea dentro (serían varios comandos): {redactar(linea)!r}")
        try:
            linea.encode(CODIFICACION)
        except UnicodeEncodeError:
            raise ValueError(f"la línea no cabe en {CODIFICACION}: {redactar(linea)!r}") from None

    def _llamar_estado(self, conectado: bool, motivo: str) -> None:
        try:
            self._al_estado(conectado, motivo)
        except Exception as exc:  # noqa: BLE001 — frontera de callback: un al_estado que falla no tumba el hilo (R-J-02)
            logger.error("al_estado falló: %s", redactar(f"{type(exc).__name__}: {exc}"))

    def _avisar(self, texto: str) -> None:
        texto = redactar(texto)
        logger.warning(texto)
        if self._al_aviso is None:
            return
        try:
            self._al_aviso(texto)
        except Exception as exc:  # noqa: BLE001 — frontera de callback: un aviso que falla no para el envío
            logger.error("al_aviso falló: %s", redactar(f"{type(exc).__name__}: {exc}"))

    def _caida_hilo(self, nombre: str, error: str, relanzado: bool) -> None:
        """Caída de un HiloVigilado (injerto §8.11): se registra y se pasa a `al_caida_hilo` si hay."""
        logger.error("hilo %s caído (%s): %s", nombre, "relanzado" if relanzado else "NO relanzado", redactar(error))
        if self._al_caida_hilo is not None:
            self._al_caida_hilo(nombre, redactar(error), relanzado)   # HiloVigilado ya protege esta llamada


# ══════════════════════════════════════════════════════════════════════
# Sombra (R-O-03)
# ══════════════════════════════════════════════════════════════════════
class ClienteSombra:
    """Fase sombra (R-O-03): lecturas al DAS real; mutantes a un `Emparejador` interno con mensajes SIMULADOS.

    SEGUNDO candado de código: los mutantes se desvían ANTES de llegar al
    cliente real (que además es `solo_lectura` y lanzaría `EnvioProhibido`).
    `al_mensaje(msg, True)` recibe cada línea sintética ya parseada; se llama
    en el hilo que envía (el principal) y debe SOLO encolar. La `latencia_s`
    del emparejador NO se aplica aquí: `enviar` nunca bloquea.

    A-07: cada mutante pasa por una `CuotaComandos` propia SOLO para CONTAR
    (no espera): si el DAS real lo habría retenido por cuota, suma
    `cuota_agotada` y llama a `al_cuota_agotada(linea_redactada, espera_s)`
    (opcional; el ejecutor lo anota en el diario como «cuota_agotada»).
    `cuota` opcional (por defecto una `CuotaComandos` con el reloj del
    cliente real); nunca la del cliente real, que usa otro hilo.
    """

    def __init__(self, real: ClienteDAS, emparejador: "Emparejador",
                 al_mensaje: Callable[[MensajeDAS, bool], None], parser: Optional[Parser] = None,
                 cuota: Optional[CuotaComandos] = None,
                 al_cuota_agotada: Optional[Callable[[str, float], None]] = None) -> None:
        if not isinstance(real, ClienteDAS):
            raise TypeError("real debe ser un ClienteDAS")
        if not real.solo_lectura:
            raise ValueError("ClienteSombra exige un ClienteDAS de solo lectura (R-O-03: en sombra nada muta DAS)")
        if not (callable(getattr(emparejador, "recibir", None)) and callable(getattr(emparejador, "tic", None))):
            raise TypeError("emparejador debe tener recibir(linea) y tic()")
        if not callable(al_mensaje):
            raise TypeError("al_mensaje debe ser una función (msg, simulado) -> None")
        if parser is not None and not isinstance(parser, Parser):
            raise TypeError("parser debe ser un protocolo.Parser")
        if cuota is not None and not (callable(getattr(cuota, "espera_para", None))
                                      and callable(getattr(cuota, "anotar", None))):
            raise TypeError("cuota debe tener espera_para(linea) y anotar(linea)")
        if cuota is not None and cuota is real._cuota:
            raise ValueError("la cuota de la sombra no puede ser la del cliente real (la usa el hilo emisor)")
        if al_cuota_agotada is not None and not callable(al_cuota_agotada):
            raise TypeError("al_cuota_agotada debe ser una función (linea, espera_s) -> None")
        self._real = real
        self._emparejador = emparejador
        self._al_mensaje = al_mensaje
        self._parser = parser or Parser(real.es_nuestro, watch=False, cuenta=real.cuenta)
        self._cerrojo = threading.Lock()                    # el parser tiene estado ($INTMSG, bloques)
        self._cuota = cuota if cuota is not None else CuotaComandos(real._reloj)
        self._al_cuota_agotada = al_cuota_agotada
        self._cuota_agotada = 0

    @property
    def real(self) -> ClienteDAS:
        return self._real

    @property
    def emparejador(self) -> "Emparejador":
        return self._emparejador

    @property
    def cuota_agotada(self) -> int:
        """A-07: mutantes que el DAS real habría retenido por cuota (la sombra no espera, solo cuenta)."""
        return self._cuota_agotada

    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> bool:
        """Mutante → `emparejador.recibir` → mensajes simulados; el resto → `real.enviar` (R-O-03, §9).

        Una línea con varios comandos dentro nunca llega al DAS real: si
        alguno es mutante, entera al emparejador. Devuelve True si el mutante
        llegó al emparejador o lo que devuelva `real.enviar` (G2-05).
        """
        if not isinstance(linea, str):
            raise TypeError(f"enviar espera una línea de texto, no {type(linea).__name__}")
        if es_mutante(linea):
            logger.info("[SOMBRA] al emparejador: %s", redactar(linea))
            self._contar_cuota(linea)
            self._entregar(self._emparejador.recibir(linea))
            return True
        return self._real.enviar(linea, serie, version)

    def tic(self) -> None:
        """`emparejador.tic()`: stops y órdenes que reposan en el libro simulado se llenan (mensajes simulados).

        Quien alimente el libro del emparejador con las cotizaciones reales
        (el ejecutor, desde `MercadoDAS`) llama a `tic()` después.
        """
        self._entregar(self._emparejador.tic())

    def conectar(self) -> bool:
        return self._real.conectar()

    def cerrar(self) -> None:
        self._real.cerrar()

    def invalidar(self, serie: str, version: int) -> None:
        self._real.invalidar(serie, version)

    @property
    def conectado(self) -> bool:
        return self._real.conectado

    @property
    def logon(self) -> dict[str, Optional[bool]]:
        return self._real.logon

    @property
    def hilos_vivos(self) -> bool:
        return self._real.hilos_vivos

    @property
    def ultimo_recibido_en(self) -> Optional[float]:
        return self._real.ultimo_recibido_en

    def _contar_cuota(self, linea: str) -> None:
        """A-07: ¿el DAS real habría esperado su cuota? Se cuenta y se avisa; la sombra NO espera."""
        try:
            espera = float(self._cuota.espera_para(linea))
            self._cuota.anotar(linea)
        except (TypeError, ValueError) as exc:  # frontera: una cuota rara no impide la simulación
            logger.error("[SOMBRA] cuota: %s", redactar(f"{type(exc).__name__}: {exc}"))
            return
        if espera <= 0:
            return
        self._cuota_agotada += 1
        texto = redactar(linea)
        logger.warning("[SOMBRA] cuota agotada: el DAS real habría retenido %.2f s: %s", espera, texto)
        if self._al_cuota_agotada is None:
            return
        try:
            self._al_cuota_agotada(texto, espera)
        except Exception as exc:  # noqa: BLE001 — frontera de callback: contar no puede parar la simulación
            logger.error("[SOMBRA] al_cuota_agotada falló: %s", redactar(f"{type(exc).__name__}: {exc}"))

    def _entregar(self, lineas: list[str]) -> None:
        for cruda in lineas:
            with self._cerrojo:
                msg = self._parser.parsear(cruda)
            try:
                self._al_mensaje(msg, True)
            except Exception as exc:  # noqa: BLE001 — frontera de callback: un mensaje simulado que falla no pierde los siguientes
                logger.error("[SOMBRA] al_mensaje falló con %s: %s", redactar(cruda),
                             redactar(f"{type(exc).__name__}: {exc}"))


def _entero_o_none(texto: str) -> Optional[int]:
    """int32 con signo o None (token de NEWORDER, id de CANCEL/REPLACE)."""
    try:
        valor = int(texto)
    except ValueError:
        return None
    return valor if -(2**31) <= valor <= 2**31 - 1 and texto.strip().lstrip("+-").isdigit() else None


def _cerrar_socket(sock: socket.socket) -> None:
    """shutdown + close sin lanzar (frontera de red): despierta al lector bloqueado en recv."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:  # frontera de red: ya estaba cerrado o nunca conectó del todo
        pass
    try:
        sock.close()
    except OSError:  # frontera de red: cerrar dos veces es inofensivo
        pass
