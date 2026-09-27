"""El lado de `bot.py` de la tubería de señales: `EnlaceEjecutor` (§3.11, §6.1).

QUÉ HACE. `EnlaceEjecutor` es el cliente de `multiprocessing.connection` que
el bot de alertas usaría (DIFERIDO, bandera `BOT_DAS_ENLACE=1`, §11.3) para
pasar al ejecutor lo que su motor ya decidió: «eventos» (los `Evento` de una
vela), «hidratado», «radar» (candidatos con la estimación de locates, con
`strategy_id` añadido por nombre, corrección 6), «latido» del feed y
«dia_nuevo». Cada método ENCOLA un diccionario y vuelve; un hilo propio
conecta con `Client` (authkey HMAC obligatoria), saluda con «hola» {versión,
hash del motor}, espera «ok» y vacía la cola. Si la conexión se cae, o el
ejecutor aún no escucha, reintenta cada `reconectar_s` (5 s) conservando
hasta `tope` (2.000) mensajes.

Además define lo que comparten los dos extremos y no necesita nada más que la
stdlib: los tipos de mensaje (`T_*`), el casado nombre → `strategy_id`
(`mapa_nombres`, `anotar_strategy_id`, `anadir_strategy_id`) y la lectura
de `BOT_DAS_TUBERIA` / `BOT_DAS_AUTHKEY`. `fuente_senales` los importa de
aquí: una sola definición del protocolo.

POR QUÉ ESTÁ AQUÍ. `bot.py` vive fuera de git y está en producción: lo que se
le injerte tiene que ser barato y no poder tumbarlo. Por eso este módulo solo
importa `app.bot_das` (VERSION), `app.bot_das.tipos` y la stdlib: ni pandas
extra, ni httpx, ni nada del ejecutor. Y por eso los métodos corren en el
hilo lector del padre sin bloquear jamás (R-M-05: la señal no espera a nadie).

LAS TRAMPAS.
  * Nada de aquí lanza hacia `bot.py` salvo el constructor ante una
    configuración imposible (sin authkey, dirección ilegible): eso es un
    error de instalación que tiene que verse al arrancar, no a las 9:30.
  * Sin authkey NO hay enlace (riesgo 19): `ValueError`. Con una clave
    incorrecta el Listener corta el saludo HMAC; aquí se cuenta y se reintenta.
  * «hola» se CONTESTA: la cola no se vacía hasta recibir «ok». Un ejecutor que
    rechaza el hash del motor (H-6) no se come los mensajes; se reintenta cada
    `reconectar_s` y, si la cola llega al tope, se tira lo MÁS VIEJO (una señal
    de hace minutos ya está caducada, R-B-04; igual criterio que el radar de
    bot_alerts_radar_proceso l.248-262) y se cuenta en `perdidos`.
  * Entrega «al menos una vez»: el mensaje que falla al enviarse vuelve a la
    cabeza de la cola. Lo que el sistema operativo aceptó y el ejecutor no llegó
    a leer antes de morir se pierde; el ejecutor deduplica por `id_evento`
    (R-A-05), así que repetir nunca duplica órdenes.
  * Un mensaje que no se puede picklar (un objeto raro en el Evento) se
    descarta y se cuenta: reencolarlo bloquearía la cola para siempre.
  * El PID/hilo: el hilo es daemon; `parar` intenta vaciar la cola `vaciar_s`
    segundos y luego cierra. Un `Client()` colgado en el saludo de un Listener
    ocupado no impide que `parar` vuelva (join con tiempo).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from multiprocessing.connection import Client
from multiprocessing.reduction import ForkingPickler
from typing import Any, Iterable, Optional

from app.bot_das import VERSION

log = logging.getLogger(__name__)

# ── protocolo de la tubería (dict con "t"; calcado de bot_alerts_alerta_proceso.py l.36-51) ──
T_HOLA = "hola"
T_OK = "ok"
T_RECHAZADO = "rechazado"
T_EVENTOS = "eventos"
T_HIDRATADO = "hidratado"
T_RADAR = "radar"
T_LATIDO = "latido"
T_DIA_NUEVO = "dia_nuevo"

DIRECCION_POR_DEFECTO: tuple[str, int] = ("127.0.0.1", 8765)   # §3.11: BOT_DAS_TUBERIA por defecto
ENTORNO_TUBERIA = "BOT_DAS_TUBERIA"
ENTORNO_AUTHKEY = "BOT_DAS_AUTHKEY"
TOPE_COLA = 2000                  # §6.1: «conserva hasta 2.000 mensajes»
RECONECTAR_S = 5.0                # §6.1: «reconecta cada 5 s»
ESPERA_OK_S = 5.0                 # cuánto espera la respuesta al «hola»
_ESPERA_COLA_S = 0.25             # granularidad con la que el hilo mira la conexión y `parando`
_PREFIJO_TUBERIA_WINDOWS = "\\\\.\\pipe\\"


# ── configuración (leída en la LLAMADA, nunca al importar) ─────────────
def authkey_valida(authkey: Any) -> bytes:
    """`bytes` no vacíos (texto → UTF-8). Vacía o None → ValueError: sin clave no hay tubería (riesgo 19, §6.1)."""
    if isinstance(authkey, str):
        authkey = authkey.encode("utf-8")
    if not isinstance(authkey, (bytes, bytearray)) or len(authkey) == 0:
        raise ValueError("authkey obligatoria (BOT_DAS_AUTHKEY): sin ella la tubería no arranca (riesgo 19)")
    return bytes(authkey)


def direccion_valida(direccion: Any) -> "tuple[str, int] | str":
    """(host, puerto) con puerto en [0, 65535], o el nombre de una tubería con nombre de Windows (texto no vacío)."""
    if isinstance(direccion, str) and direccion:
        return direccion
    if (isinstance(direccion, (tuple, list)) and len(direccion) == 2 and isinstance(direccion[0], str)
            and direccion[0] and type(direccion[1]) is int and 0 <= direccion[1] <= 65535):
        return (direccion[0], direccion[1])
    raise ValueError(f"direccion debe ser (host, puerto) o un nombre de tubería: {direccion!r}")


def direccion_de_texto(texto: str) -> "tuple[str, int] | str":
    """`"host:puerto"` → (host, puerto); `r"\\\\.\\pipe\\nombre"` → tal cual. Otra cosa → ValueError (§3.11, BOT_DAS_TUBERIA).

    El puerto se separa por el ÚLTIMO «:» para no confundir un host con dos
    puntos; debe ser un entero decimal en [1, 65535] (0 = «cualquiera» no
    sirve para que el otro extremo sepa dónde conectar).
    """
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError(f"{ENTORNO_TUBERIA} vacía o no es texto: {texto!r}")
    texto = texto.strip()
    if texto.startswith(_PREFIJO_TUBERIA_WINDOWS):
        return texto
    host, sep, puerto = texto.rpartition(":")
    if not sep or not host or not puerto.isdigit():
        raise ValueError(f"{ENTORNO_TUBERIA} debe ser «host:puerto» o «\\\\.\\pipe\\nombre»: {texto!r}")
    numero = int(puerto)
    if not 1 <= numero <= 65535:
        raise ValueError(f"{ENTORNO_TUBERIA}: puerto fuera de rango: {texto!r}")
    return (host, numero)


def direccion_de_entorno() -> "tuple[str, int] | str":
    """`BOT_DAS_TUBERIA` si está (y no vacía); si no, ("127.0.0.1", 8765) (§3.11)."""
    texto = os.environ.get(ENTORNO_TUBERIA, "")
    return direccion_de_texto(texto) if texto.strip() else DIRECCION_POR_DEFECTO


def authkey_de_entorno() -> bytes:
    """`BOT_DAS_AUTHKEY` en UTF-8; ausente o vacía → ValueError (riesgo 19)."""
    return authkey_valida(os.environ.get(ENTORNO_AUTHKEY, ""))


# ── casado nombre → strategy_id (corrección 6, riesgo 25) ──────────────
def mapa_nombres(estrategias: Iterable[dict]) -> tuple[dict[str, str], set[str]]:
    """{nombre: strategy_id} de `runner.motor.estrategias` y el conjunto de nombres AMBIGUOS (corrección 6).

    `estimar_por_estrategia` (engine l.549-602) devuelve filas con `nombre` y
    SIN `strategy_id`. Un nombre es ambiguo si aparece con DOS `strategy_id`
    distintos: no hay forma segura de casar su fila y no está en el mapa. La
    misma estrategia repetida por cuenta (multicuenta, 18-sep) lleva el mismo
    id y NO es ambigua. Entradas sin nombre o sin id se ignoran.
    """
    mapa: dict[str, str] = {}
    repetidos: set[str] = set()
    for e in estrategias:
        if not isinstance(e, dict):
            continue
        nombre, sid = e.get("name"), e.get("strategy_id")
        if not isinstance(nombre, str) or not nombre or not isinstance(sid, str) or not sid:
            continue
        if nombre in mapa and mapa[nombre] != sid:
            repetidos.add(nombre)
            continue
        mapa[nombre] = sid
    for nombre in repetidos:
        mapa.pop(nombre, None)
    return mapa, repetidos


def anotar_strategy_id(filas: Iterable[Any], nombre_a_id: dict[str, str],
                       repetidos: Iterable[str] = ()) -> list[dict]:
    """Copia de cada fila (dict) con `strategy_id` añadido si su `nombre` casa de forma unívoca; si no, la copia va SIN él.

    La fila original no se muta. Un `strategy_id` que ya trajera la fila se
    borra de la copia antes de casar: solo vale el que sale del mapa. Las
    filas que no son dict se omiten. Lo usa el enlace: el ejecutor, al ver
    una fila sin `strategy_id`, la descarta y AVISA (riesgo 25), así el fallo
    se ve en el lado que decide.
    """
    ambiguos = set(repetidos)
    salida: list[dict] = []
    for fila in filas or ():
        if not isinstance(fila, dict):
            continue
        copia = dict(fila)
        copia.pop("strategy_id", None)
        nombre = copia.get("nombre")
        if isinstance(nombre, str) and nombre not in ambiguos and nombre in nombre_a_id:
            copia["strategy_id"] = nombre_a_id[nombre]
        salida.append(copia)
    return salida


def anadir_strategy_id(filas: Iterable[Any], nombre_a_id: dict[str, str],
                       repetidos: Iterable[str] = ()) -> tuple[list[dict], list[str]]:
    """(filas con `strategy_id`, nombres descartados) (corrección 6, riesgo 25).

    Una fila que no se puede casar de forma unívoca (nombre repetido con ids
    distintos o desconocido) NO viaja: comprar locates para la estrategia
    equivocada es peor que no comprarlos. Casar por posición sería frágil.
    """
    validas: list[dict] = []
    descartados: list[str] = []
    ambiguos = set(repetidos)
    for fila in filas or ():
        nombre = fila.get("nombre") if isinstance(fila, dict) else None
        anotada = anotar_strategy_id([fila], nombre_a_id, ambiguos)
        if anotada and "strategy_id" in anotada[0]:
            validas.append(anotada[0])
        else:
            descartados.append(str(nombre))
    return validas, descartados


# ── el enlace ──────────────────────────────────────────────────────────
class EnlaceEjecutor:
    """Cliente de la tubería de señales, lado `bot.py` (§3.11, §6.1). Métodos que encolan y vuelven; un hilo envía.

    `direccion`/`authkey` None → `BOT_DAS_TUBERIA` (defecto ("127.0.0.1", 8765))
    y `BOT_DAS_AUTHKEY` (obligatoria) leídas AQUÍ, no al importar.
    `reconectar_s` y `espera_ok_s` existen para los tests; en producción
    valen 5 s (§6.1).
    """

    def __init__(self, direccion: Any = None, authkey: Any = None, tope: int = TOPE_COLA,
                 version: str = VERSION, motor_hash: str = "",
                 reconectar_s: float = RECONECTAR_S, espera_ok_s: float = ESPERA_OK_S) -> None:
        self.direccion = direccion_valida(direccion) if direccion is not None else direccion_de_entorno()
        self._authkey = authkey_valida(authkey) if authkey is not None else authkey_de_entorno()
        if type(tope) is not int or tope < 1:
            raise ValueError(f"tope debe ser un entero ≥ 1: {tope!r}")
        if not isinstance(version, str) or not version:
            raise ValueError(f"version debe ser texto no vacío: {version!r}")
        if not isinstance(motor_hash, str):
            raise ValueError(f"motor_hash debe ser texto: {motor_hash!r}")
        if not reconectar_s > 0 or not espera_ok_s > 0:
            raise ValueError("reconectar_s y espera_ok_s deben ser > 0")
        self.tope = tope
        self.version = version
        self.motor_hash = motor_hash
        self.reconectar_s = float(reconectar_s)
        self.espera_ok_s = float(espera_ok_s)
        self._cola: deque = deque()
        self._cond = threading.Condition(threading.Lock())
        self._parando = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._conn: Any = None
        self._en_vuelo = False
        self.encolados = 0
        self.enviados = 0
        self.perdidos = 0
        self.impicklables = 0
        self.conexiones = 0
        self.desconexiones = 0
        self.rechazos = 0
        self.intentos_fallidos = 0
        self.motivo_rechazo: Optional[str] = None
        self.ultimo_error: Optional[str] = None
        self.ultimo_envio_en: Optional[float] = None

    # ── ciclo de vida ──
    def arrancar(self) -> None:
        """Arranca el hilo `enlace-ejecutor` (daemon). Idempotente."""
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._parando.clear()
        self._hilo = threading.Thread(target=self._bucle, name="enlace-ejecutor", daemon=True)
        self._hilo.start()

    def parar(self, vaciar_s: float = 2.0, espera_s: float = 5.0) -> None:
        """Intenta vaciar la cola durante `vaciar_s` (si hay conexión), para el hilo y cierra. Idempotente; nunca lanza."""
        limite = time.monotonic() + max(float(vaciar_s), 0.0)
        while time.monotonic() < limite and self.conectado and (self.pendientes > 0 or self._en_vuelo):
            time.sleep(0.02)
        self._parando.set()
        with self._cond:
            self._cond.notify_all()
        hilo = self._hilo
        if hilo is not None and hilo is not threading.current_thread():
            hilo.join(timeout=max(float(espera_s), 0.0))
        self._cerrar_conexion()

    @property
    def conectado(self) -> bool:
        return self._conn is not None

    @property
    def pendientes(self) -> int:
        with self._cond:
            return len(self._cola)

    def salud(self) -> dict:
        """Contadores para el log de `bot.py`; no toca la conexión."""
        return {
            "viva": bool(self._hilo is not None and self._hilo.is_alive()),
            "conectado": self.conectado, "pendientes": self.pendientes, "encolados": self.encolados,
            "enviados": self.enviados, "perdidos": self.perdidos, "impicklables": self.impicklables,
            "conexiones": self.conexiones, "desconexiones": self.desconexiones, "rechazos": self.rechazos,
            "intentos_fallidos": self.intentos_fallidos, "motivo_rechazo": self.motivo_rechazo,
            "ultimo_error": self.ultimo_error, "ultimo_envio_en": self.ultimo_envio_en,
        }

    # ── lo que llama bot.py (encola y vuelve; §3.11) ──
    def eventos(self, ticker: str, minuto: str, timestamp: Any, eventos: list, recuperada: bool) -> None:
        """«eventos» {ticker, minuto, timestamp, eventos, recuperada}: los `Evento` de una vela, tal cual (viajan picklados, §6.1)."""
        self._encolar({"t": T_EVENTOS, "ticker": ticker, "minuto": minuto, "timestamp": timestamp,
                       "eventos": list(eventos or []), "recuperada": bool(recuperada)})

    def hidratado(self, ticker: str, n_velas: int, eventos: list, prev_close: Any) -> None:
        """«hidratado» {ticker, n_velas, eventos, prev_close}: resultado de hidratar un ticker (memoria ELMT: sus eventos son PRESENTE)."""
        self._encolar({"t": T_HIDRATADO, "ticker": ticker, "n_velas": n_velas,
                       "eventos": list(eventos or []), "prev_close": prev_close})

    def radar(self, candidatos: list, nombre_a_id: dict[str, str], repetidos: Iterable[str] = ()) -> None:
        """«radar» {candidatos: [{ticker, precio, estimacion}]} con `strategy_id` añadido por nombre a cada fila (corrección 6).

        `nombre_a_id` y `repetidos` salen de `mapa_nombres(runner.motor.estrategias)`.
        Las filas que no casan viajan SIN `strategy_id`: el ejecutor las
        descarta y avisa (riesgo 25). Candidatos que no son dict se omiten.
        """
        salida = []
        for c in list(candidatos or []):
            if not isinstance(c, dict):
                continue
            salida.append(dict(c, estimacion=anotar_strategy_id(c.get("estimacion") or [], nombre_a_id or {},
                                                                repetidos)))
        self._encolar({"t": T_RADAR, "candidatos": salida})

    def latido(self, ultima_vela_en: Optional[float], feed_vivo: bool) -> None:
        """«latido» {ultima_vela_en, feed_vivo} cada 5 s desde bot.py (F11 b, R-J-01)."""
        self._encolar({"t": T_LATIDO, "ultima_vela_en": ultima_vela_en, "feed_vivo": bool(feed_vivo)})

    def dia_nuevo(self) -> None:
        """«dia_nuevo»: el motor de bot.py se reinició."""
        self._encolar({"t": T_DIA_NUEVO})

    # ── tripas ──
    def _encolar(self, msg: dict) -> None:
        """O(1) bajo un cerrojo que el hilo solo retiene para sacar un elemento. Cola llena → se tira el MÁS VIEJO."""
        with self._cond:
            if len(self._cola) >= self.tope:
                self._cola.popleft()
                self.perdidos += 1
                if self.perdidos == 1 or self.perdidos % 500 == 0:
                    log.warning("[ENLACE] cola al tope (%d): %d mensaje(s) viejo(s) tirado(s)", self.tope, self.perdidos)
            self._cola.append(msg)
            self.encolados += 1
            self._cond.notify()

    def _bucle(self) -> None:
        """Cuerpo del hilo: conectar → saludar → vaciar; ante cualquier fallo de red, cerrar y reintentar a los `reconectar_s`."""
        while not self._parando.is_set():
            try:
                if self._conn is None and not self._conectar():
                    self._parando.wait(self.reconectar_s)
                    continue
                self._vaciar()
            except Exception as exc:  # noqa: BLE001 — frontera de red (§6.1): el enlace nunca muere; cierra, cuenta y reintenta a los 5 s
                self.ultimo_error = f"{type(exc).__name__}: {exc}"
                if self._conn is not None:
                    self.desconexiones += 1
                    log.warning("[ENLACE] conexión con el ejecutor perdida (%s); reintento en %.0f s",
                                self.ultimo_error, self.reconectar_s)
                self._cerrar_conexion()
                self._parando.wait(self.reconectar_s)

    def _conectar(self) -> bool:
        """`Client` + «hola» + espera «ok». False si no escucha, la clave no casa o rechaza el saludo (H-6)."""
        try:
            conn = Client(self.direccion, authkey=self._authkey)
        except Exception as exc:  # noqa: BLE001 — frontera de red: ejecutor apagado (ConnectionRefused) o clave distinta (AuthenticationError)
            self.intentos_fallidos += 1
            self.ultimo_error = f"conectar: {type(exc).__name__}: {exc}"
            return False
        try:
            conn.send({"t": T_HOLA, "version": self.version, "motor_hash": self.motor_hash})
            if not conn.poll(self.espera_ok_s):
                raise TimeoutError(f"sin respuesta al «hola» en {self.espera_ok_s:.1f} s")
            resp = conn.recv()
        except Exception as exc:  # noqa: BLE001 — frontera de red: el ejecutor cortó durante el saludo
            self.intentos_fallidos += 1
            self.ultimo_error = f"saludo: {type(exc).__name__}: {exc}"
            _cerrar(conn)
            return False
        if isinstance(resp, dict) and resp.get("t") == T_OK:
            self._conn = conn
            self.conexiones += 1
            self.motivo_rechazo = None
            log.info("[ENLACE] conectado con el ejecutor en %s (versión %s)", self.direccion, resp.get("version"))
            return True
        self.rechazos += 1
        self.motivo_rechazo = str(resp.get("motivo")) if isinstance(resp, dict) else repr(resp)
        self.ultimo_error = f"rechazado: {self.motivo_rechazo}"
        if self.rechazos == 1 or self.rechazos % 60 == 0:
            log.warning("[ENLACE] el ejecutor RECHAZA el enlace: %s", self.motivo_rechazo)
        _cerrar(conn)
        return False

    def _vaciar(self) -> None:
        """Manda la cola mientras haya conexión. Sin nada que mandar, mira cada 0,25 s si el ejecutor cerró (EOF)."""
        conn = self._conn
        while not self._parando.is_set():
            with self._cond:
                if not self._cola:
                    self._cond.wait(_ESPERA_COLA_S)
                msg = self._cola.popleft() if self._cola else None
                self._en_vuelo = msg is not None
            if msg is None:
                if conn.poll(0):             # el ejecutor no manda nada tras «ok»: si hay algo legible es EOF
                    conn.recv()              # EOFError → frontera en _bucle
                continue
            try:
                datos = bytes(ForkingPickler.dumps(msg))
            except Exception as exc:  # noqa: BLE001 — frontera de mensaje: un objeto no picklable no puede atascar la cola
                self._en_vuelo = False
                self.impicklables += 1
                self.ultimo_error = f"mensaje no picklable ({msg.get('t')!r}): {type(exc).__name__}: {exc}"
                log.warning("[ENLACE] %s", self.ultimo_error)
                continue
            try:
                conn.send_bytes(datos)
            except BaseException:
                self._devolver(msg)
                raise
            finally:
                self._en_vuelo = False
            self.enviados += 1
            self.ultimo_envio_en = time.time()

    def _devolver(self, msg: dict) -> None:
        """El mensaje que no salió vuelve a la CABEZA (orden intacto); si la cola ya está al tope, se cuenta como perdido."""
        with self._cond:
            if len(self._cola) >= self.tope:
                self.perdidos += 1
            else:
                self._cola.appendleft(msg)

    def _cerrar_conexion(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            _cerrar(conn)


def _cerrar(conn: Any) -> None:
    try:
        conn.close()
    except OSError:   # frontera de red: cerrar una conexión ya muerta no es un error
        return
