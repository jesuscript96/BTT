"""Todo lo que viaja entre módulos del bot de ejecución en DAS.

QUÉ HACE. Dataclasses, enumeraciones y constantes por defecto del libro de
reglas. Sin lógica salvo la validación de los constructores y la regla del
tick, que es la única aritmética que necesita todo el mundo.

POR QUÉ EN UN SOLO FICHERO. El decisor, el diario, el vigilante y los tests
hablan del mismo objeto; un campo nuevo se ve aquí y en ningún otro sitio.
Los módulos de `reglas/` importan de aquí y de nada más. Por el ajuste (a)
del orquestador, `Ficha`, `NivelesStop` y `StopDeseado` también viven aquí
(los importan `referencia_massive.py` y `reglas/stops.py`).

LAS TRAMPAS.
  * Precios en `Decimal`, nunca `float`: 10 * 1.03 = 10.299999… y DAS recibe
    «10.3» o nada. Todo precio que entra por el socket se construye con
    `Decimal(cadena)` y todo el que sale pasa por `protocolo.formatear_precio`,
    que LANZA si no está al tick (injerto A §8.1).
  * Acciones en `int`. El `Evento` del motor trae `acciones` como float
    redondeado (`bot_alerts_engine.py` l.1208-1210); la conversión a int se
    hace UNA vez en `reglas.entrada.qty_final` y `OrdenNueva` rechaza lo demás.
  * `neta` de una posición es SIGNADA en todo el bot: corto = negativo. Lo que
    DAS envíe en `%POS` (signo no documentado) lo normaliza `protocolo`.
  * Un `Decimal` no finito (NaN, Infinity) NO es un precio: `tick_de` y
    `al_tick` lanzan `ValueError` y `en_tick` devuelve False, en vez de dejar
    que `decimal` señale `InvalidOperation` en una comparación. La única
    puerta de entrada de floats es `reglas.precios.de_float`, que ya los
    rechaza; esto es la segunda red.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import Enum, IntEnum
from typing import Any, Optional

# ── constantes por defecto del libro (VIGENTES; los defaults del cuadro salen de aquí) ──
STOP_LIMITE_PCT = Decimal("50")                 # R-C-01 v4 (Jaume 29-sep, stop único): UN stop por nivel, disparo en L, límite L + 50 %
STOP_PROTECCION_PCT = Decimal("25")             # R-C-10 (4): 20-30 % para posiciones desconocidas
STOP_MARGEN_BAJO_LIMIT_UP_PCT = Decimal("1.5")  # R-F-02: 1-2 % bajo la banda
ENTRADA_AGREGAR_S = 15                          # R-B-01 v3 / decisión 56 (Jaume 1-oct): 15 s agregando en el punto medio
ENTRADA_TOPE_CAIDA_BID_PCT = Decimal("3")       # R-B-01 v3: no cruzar si el bid cayó > 3 %
ENTRADA_CRUCE_BAJO_BID_PCT = Decimal("0.5")     # R-B-01 v3: cruzar a bid × (1 − 0,5 %)
ENTRADA_CADUCIDAD_S = 60                        # R-B-04
ENTRADA_RETRASO_MAX_PCT = Decimal("1")          # R-A-01 (provisional)
ENTRADA_DISTANCIA_ULTIMO_BID_PCT: Optional[Decimal] = None  # B20 bis APAGADA (decisión 11, Jaume 30-sep: «la quito porque ya tenemos el 3 %»); un número la enciende
ENTRADA_REINTENTOS_RECHAZO = 2                  # R-B-07
SALIDA_ANTICIPO_S = 60                          # R-D-08 / R-D-02
EOD_COMPROBAR_DESPUES_S = 30                    # R-D-02
TP_TECHO_ASK_PCT = Decimal("3")                 # R-D-03 v2
CERRAR_TODO_TECHO_PCT = Decimal("5")            # R-D-06
CERRAR_TODO_REINTENTOS = 2                      # R-D-06
PERSEGUIR_ASK_MAX = 3                           # F5 (corrección del juez): a la hora, como mucho 3 REPLACE de precio
HALT_K_MAX = 3                                  # R-F-01
HALT_DISTANCIA_BANDA_K2_PCT = Decimal("4")      # R-F-01: 3-5 %
HALT_PRIMERA_VELA_MAX_PCT = Decimal("6")        # R-F-01 esc. 2 / R-F-03 / R-F-04
HALT_T1_SUBIDA_MAX_PCT = Decimal("250")         # R-F-05
HALT_ENVIAR_ANTES_FIN_S = 60                    # R-F-01 (22/24-sep)
LOCATES_TOPE_GASTO_PCT = Decimal("3")           # R-H-03
LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT = Decimal("30")  # H6
LOCATES_INQUIRE_S = 3.0                         # manual L2000 (1 cada 3 s)
MODO_SEGURIDAD_PRECIO_MIN = Decimal("5")        # R-I-04
MODO_SEGURIDAD_DOLLAR_VOLUME_MIN = Decimal("2000000")  # R-I-04
FEED_PREALERTA_S = 30                           # R-J-01
FEED_EMERGENCIA_S = 60                          # R-J-01
DAS_RECONEXION_S = (2.0, 4.0, 8.0, 16.0)        # R-J-02 (luego 30 s sin parar)
DAS_RECONEXION_TOPE_S = 30.0
DAS_AVISO_CADA_S = 300                          # R-J-02 (3)
RELANZAR_S = (1.0, 2.0, 5.0, 10.0)              # R-J-04 v2 (luego cada 10 s)
LATIDO_S = 1.0                                  # R-J-04 v2
COLGADO_S = 3.0                                 # R-J-04 v2
PING_EXTERNO_S = 60                             # R-J-05
PING_FALLOS_ALARMA = 3                          # R-J-05
RELOJ_NEGARSE_S = 2.0                           # R-J-07
RELOJ_AVISO_S = 0.5                             # R-J-07
DISCO_MIN_GB = 5                                # R-J-07
BARRIDO_TRAS_FILL_S = 1.0                       # R-K-01 (21-sep)
BARRIDO_CON_POSICIONES_S = 2.0
BARRIDO_SIN_NADA_S = 10.0
BARRIDO_VENTANA_TRAS_FILL_S = 60.0
RECONCILIACION_CADUCA_S = 30.0                  # R-K-03
BS_PRIMEROS_INFORMES = 5                        # R-G-01 v2 (22-sep): 1 min × 5, luego cada 5 min
BS_CADENCIA_INICIAL_S = 60
BS_CADENCIA_DESPUES_S = 300
FILTRO_PRINTS_MS = 20                           # R-A-06
IPO_DIAS = 30                                   # R-A-03 v2
SPAC_SIC = ("6770",)                            # R-A-03 v2
OPA_BANDA_MIN = 30                              # R-A-03 v2
OPA_RANGO_MAX_PCT = Decimal("1.5")
OPA_DOLARES_MIN = Decimal("100000")
STOP_REINTENTOS = 5                             # R-C-03 (1)
STOP_VENTANA_MIN = 5                            # R-C-03 (3) — solo se registra, NO se cierra (prima R-B-07/EP-1)
STOP_COMPROBACION_S = 1.0                       # R-C-04
STOP_DEBOUNCE_S = 0.3                           # técnico (F1.6): coalescer REPLACE de stops; NUNCA en el primer fill
PLAN_B_LATIDO_S = 3.0                           # vigilancia: actúa si el ejecutor calla > 3 s
PLAN_B_DESCUBIERTA_S = 5.0                      # vigilancia: o si una posición lleva > 5 s descubierta con el ejecutor vivo
MAX_LV1 = 100                                   # manual L1996: símbolos Lv1 por defecto
COTIZACION_FRESCA_MAX_S = 5.0                   # D1-12: edad máx. de la cotización (mercado_das.FRESCA_MAX_S y entrada comprobación 8)
REPLACE_SHARE_ES_ABIERTA = True                 # A-02: defecto de `stops.replace_share_es_abierta` (el canario de comprobar_das lo confirma)
COLA_AVISOS_TOPE = 10_000
COLA_SALIDA_TOPE = 1_000


# ── enumeraciones ──────────────────────────────────────────────────────
class Fase(str, Enum):             # R-O-03 (demo DESCARTADA 24-sep)
    SOMBRA = "sombra"
    CANARIO = "canario"
    REAL = "real"


class Lado(str, Enum):             # manual L671-694
    COMPRA = "B"
    VENTA = "S"
    CORTO = "SS"


class TipoOrden(str, Enum):        # manual L618-624
    LIMITE = "LMT"
    MERCADO = "MKT"
    STOP_LIMITE_PP = "STOPLMTP"


class EstadoOrden(str, Enum):      # manual L379-405, conjunto CERRADO
    CLOSED = "Closed"
    HOLD = "Hold"
    SENDING = "Sending"
    ACCEPTED = "Accepted"
    CANCELED = "Canceled"
    REJECTED = "Rejected"
    EXECUTED = "Executed"
    PARTIAL = "Partial"
    TRIGGERED = "Triggered"
    DESCONOCIDO = "?"


class Proposito(str, Enum):        # por qué existe una orden nuestra (va al diario; el vigilante lo infiere si no lo tiene)
    ENTRADA_AGREGAR = "entrada_agregar"
    ENTRADA_CRUCE = "entrada_cruce"
    STOP = "stop"                                  # R-C-01 v4 (Jaume 29-sep): el stop ÚNICO de cada nivel L
    STOP_PROTECCION = "stop_proteccion"
    TP_AGREGAR = "tp_agregar"
    TP_CRUCE = "tp_cruce"
    HORA_AGREGAR = "hora_agregar"                  # R-D-08 (salida por hora y EOD)
    HORA_ASK = "hora_ask"
    SALIDA_MOTOR_AGREGAR = "salida_motor_agregar"  # Signal/Trailing/Time Limit (pregunta 3 a Jaume)
    SALIDA_MOTOR_CRUCE = "salida_motor_cruce"
    HALT_OPEN = "halt_open"
    HALT_PM_LIMITE = "halt_pm_limite"
    HALT_BANDA = "halt_banda"
    VENTA_EXCESO = "venta_exceso"
    CIERRE_HUMANO = "cierre_humano"
    CIERRE_REINICIO = "cierre_reinicio"            # R-E-03
    DESCONOCIDA = "desconocida"


class Origen(IntEnum):             # primer dígito del token
    EJECUTOR = 1
    VIGILANTE = 2
    EJECUTOR_LOCATE = 3


class Nivel(IntEnum):              # R-M-01
    INFO = 1
    AVISO = 2
    MAXIMO = 3


class Grupo(str, Enum):            # R-M-05
    A = "A"
    B = "B"


class EstadoLote(str, Enum):
    ABRIENDO = "abriendo"
    ABIERTO = "abierto"
    CERRANDO = "cerrando"
    CERRADO = "cerrado"
    CANCELADO = "cancelado"


class FaseIntento(str, Enum):
    AGREGANDO = "agregando"
    CANCELANDO = "cancelando"
    CRUZANDO = "cruzando"
    TERMINADO = "terminado"


class ClaseSalida(str, Enum):      # ver reglas.salidas.clasificar (cubre TODOS los literales de portfolio_sim.py)
    TP = "tp"
    HORA = "hora"
    EOD = "eod"
    STOP = "stop"
    STOP_LOTE = "stop_lote"
    REDUCE = "reduce"
    MOTOR = "motor"                # Signal / Trailing / Time Limit / Escalera / "?" → como R-D-03 (pregunta 3 a Jaume)
    HALT = "halt"
    BS = "bs"
    DAILY_LIMIT = "daily_limit"    # Daily Limit → se ignora + aviso (I1: sin cortacircuito)


class EstadoTicker(str, Enum):
    NORMAL = "normal"
    PAUSADO = "pausado"
    BS = "cisne_negro"
    SIN_SIMBOLO = "sin_simbolo"
    HALT = "halt"
    CONTROL_HUMANO = "control_humano"


# ── tick: la única aritmética compartida (regla 612 y < 1 $ a 0,0001) ──
TICK_GE_1 = Decimal("0.01")
TICK_LT_1 = Decimal("0.0001")


def tick_de(precio: Decimal) -> Decimal:
    """Tamaño de tick: ≥ 1 $ céntimos; < 1 $ diezmilésimas (regla 612).

    Lanza `ValueError` con un Decimal no finito: NaN o Infinity no tienen tick
    y una comparación con ellos señalaría `InvalidOperation` en vez de un
    error legible (trampa del módulo).
    """
    if not precio.is_finite():
        raise ValueError(f"precio no finito: {precio!r}")
    return TICK_GE_1 if precio >= 1 else TICK_LT_1


def en_tick(precio: Decimal) -> bool:
    """True si `precio` es múltiplo exacto de su tick (lo exige OrdenNueva).

    Un precio no finito, cero o negativo nunca está al tick: devuelve False
    (no lanza) para que `OrdenNueva.__post_init__` produzca su `ValueError`.
    """
    return precio.is_finite() and precio > 0 and (precio % tick_de(precio)) == 0


def al_tick(precio: Decimal, arriba: bool) -> Decimal:
    """Redondea al tick hacia ARRIBA (venta al punto medio) o ABAJO (compra).

    El tick es el del precio de ENTRADA: 0,99995 redondeado arriba da 1,0000
    (que también está al tick de céntimos). `tick_de` lanza `ValueError` si el
    precio no es finito.
    """
    t = tick_de(precio)
    return (precio / t).to_integral_value(rounding=ROUND_CEILING if arriba else ROUND_FLOOR) * t


def share_de_replace(abierta: int, llenas: int = 0,
                     share_es_abierta: bool = REPLACE_SHARE_ES_ABIERTA) -> int:
    """A-02: el `share` de un REPLACE a partir de la cantidad ABIERTA que se quiere dejar viva.

    El manual no aclara si `share` es la cantidad abierta nueva o la total
    (llenas + abierta). Un único helper para el decisor, las reglas y el
    simulador, gobernado por `stops.replace_share_es_abierta`:
      * True  → share = abierta            (lectura actual del simulador)
      * False → share = llenas + abierta   (DAS lo trata como total)
    `abierta` debe ser int > 0 (dejar 0 vivas es un Cancelar, no un REPLACE) y
    `llenas` int ≥ 0; lo demás lanza `ValueError`.
    """
    if type(abierta) is not int or abierta <= 0:
        raise ValueError(f"abierta debe ser int > 0, no {abierta!r}")
    if type(llenas) is not int or llenas < 0:
        raise ValueError(f"llenas debe ser int ≥ 0, no {llenas!r}")
    return abierta if share_es_abierta else llenas + abierta


# ── lo que llega de DAS ya parseado (protocolo.py) ────────────────────
@dataclass(frozen=True)
class MensajeDAS:                  # base; `cruda` SIEMPRE se conserva para el diario
    cruda: str


@dataclass(frozen=True)
class MsgOrden(MensajeDAS):        # %ORDER / %IORDER (manual L343-405); 15 o 19 campos
    id: int
    token: Optional[int]
    ticker: str
    lado: str
    tipo: str
    qty: int
    lvqty: int
    cxlqty: int
    precio: Decimal
    ruta: str
    estado: EstadoOrden
    hora: str
    origoid: int
    cuenta: str
    trader: str
    order_src: Optional[str]
    tif: Optional[str]
    pref: Optional[str]
    watch: bool


@dataclass(frozen=True)
class MsgOrderAct(MensajeDAS):     # %OrderAct (L434-494); `lado` normalizado a B/S/SS; `notas` texto libre
    id: int
    accion: str
    lado: str
    ticker: str
    qty: int
    precio: Decimal
    ruta: str
    hora: str
    notas: str
    token: Optional[int]


@dataclass(frozen=True)
class MsgTrade(MensajeDAS):        # %TRADE (L495-539, 8 u 11 campos) y %ITRADE (L1444-1458: OTRO orden de campos, rama de parser propia)
    id: int
    ticker: str
    lado: str
    qty: int
    precio: Decimal
    ruta: str
    hora: str
    id_orden: int
    liq: Optional[str]
    ecn_fee: Optional[Decimal]
    pl: Optional[Decimal]
    cuenta: Optional[str]
    trader: Optional[str]
    watch: bool


@dataclass(frozen=True)
class MsgPos(MensajeDAS):          # %POS / %IPOS (L256-323). `qty_cruda` tal cual; `neta` SIGNADA (corto < 0) por protocolo.normalizar_pos
    ticker: str
    tipo: int
    qty_cruda: int
    neta: int
    avg: Decimal
    init_qty: int
    init_precio: Decimal
    realizado: Decimal
    creada: str
    no_realizado: Optional[Decimal]
    watch: bool


@dataclass(frozen=True)
class MsgQuote(MensajeDAS):        # $Quote: PARCHE (L1268-1269), solo las claves presentes; valores sin convertir
    ticker: str
    campos: dict[str, str]


@dataclass(frozen=True)
class MsgBP(MensajeDAS):
    bp: Decimal
    bp_overnight: Decimal


@dataclass(frozen=True)
class MsgShortInfo(MensajeDAS):    # $SHORTINFO (L1017-1030); reg_sho opcional
    ticker: str
    shortable: bool
    short_size: int
    marginable: bool
    tasa_larga: Decimal
    tasa_corta: Decimal
    prohibido: bool
    reg_sho: Optional[bool]


@dataclass(frozen=True)
class MsgStInfoEx(MensajeDAS):     # $STINFOEX (L1064-1078): texto libre → {"ConcLong": 200, "ConcShr": 50}
    ticker: str
    valores: dict[str, Decimal]
    texto: str


@dataclass(frozen=True)
class MsgLDLU(MensajeDAS):
    ticker: str
    limit_down: Decimal
    limit_up: Decimal


@dataclass(frozen=True)
class MsgIssueStatus(MensajeDAS):  # $IssueStatus / $SymStatus (L1101-1133); TA ausente = normal
    ticker: str
    ssr: Optional[bool]
    ta: Optional[str]
    tat: Optional[str]


@dataclass(frozen=True)
class MsgAccountInfo(MensajeDAS):  # $AccountInfo (L1143-1158), 10 números
    open_eq: Decimal
    curr_eq: Decimal
    realizado: Decimal
    no_realizado: Decimal
    net: Decimal
    htb: Decimal
    sec: Decimal
    finra: Decimal
    ecn: Decimal
    comision: Decimal


@dataclass(frozen=True)
class MsgSLRet(MensajeDAS):        # %SLRET (L1701-1720); cuenta opcional; notas con espacios
    tipo: int
    ticker: str
    precio: Decimal
    tamano: int
    ruta: str
    notas: str
    cuenta: Optional[str]


@dataclass(frozen=True)
class MsgSLOrder(MensajeDAS):      # %SLOrder (L1722-1795)
    id: int
    ticker: str
    pedidas: int
    abiertas: int
    localizadas: int
    precio: Decimal
    estado: str
    ruta: str
    hora: str
    limite: Optional[Decimal]
    token: Optional[int]
    notas: str


@dataclass(frozen=True)
class MsgSLReuse(MensajeDAS):
    ticker: str
    reutilizable: bool


@dataclass(frozen=True)
class MsgSLAvail(MensajeDAS):
    cuenta: str
    ticker: str
    disponibles: int


@dataclass(frozen=True)
class MsgSLMinCharge(MensajeDAS):  # con o sin `$` (L1833-1836)
    ruta: str
    minimo: Decimal


@dataclass(frozen=True)
class MsgRouteStatus(MensajeDAS):
    ruta: str
    habilitada: bool


@dataclass(frozen=True)
class MsgConexion(MensajeDAS):     # las 12 líneas de L1472-1490, comparadas ENTERAS
    servidor: str                  # ("OrderServer", "Lost Connection")
    evento: str


@dataclass(frozen=True)
class MsgLogin(MensajeDAS):        # resultado del LOGIN (visto en DAS real 01-oct): «#LOGIN SUCCESSED» / «ERROR:<motivo>»
    ok: bool
    motivo: str                    # «SUCCESSED», «INVALID PASSWORD», …: el texto de DAS, NUNCA la clave


@dataclass(frozen=True)
class MsgMarcador(MensajeDAS):     # "#POS","#POSEND", "#Order", "#OrderEnd", "#Trade", "#TradeEnd", "#SLOrder", "#SLOrderEnd", "#buyingpower"
    nombre: str


@dataclass(frozen=True)
class MsgTS(MensajeDAS):           # $T&S (L1317-1360); condicion como entero (presunción, se valida en canario)
    ticker: str
    precio: Decimal
    volumen: int
    flag: str
    hora: str
    bolsa: str
    lado: str
    condicion: int


@dataclass(frozen=True)
class MsgBar(MensajeDAS):          # $Bar (L1373-1435): High Low Open Close (en ese orden)
    ticker: str
    cuando: str
    high: Decimal
    low: Decimal
    open: Decimal
    close: Decimal
    volumen: int
    min_type: Optional[int]


@dataclass(frozen=True)
class MsgIntMsg(MensajeDAS):       # $INTMSG multilínea acumulado por el parser con estado
    campos: dict[str, str]


@dataclass(frozen=True)
class MsgInformativo(MensajeDAS):  # ECHO, CLIENT, $TopLst, $Lv2 y cualquier `#…` no listado: se registran y nada más
    palabra: str


@dataclass(frozen=True)
class MsgDesconocido(MensajeDAS):
    palabra: str


# ── lo que envía el bot (protocolo.py lo serializa) ────────────────────
@dataclass(frozen=True)
class OrdenNueva:
    token: int
    lado: Lado
    ticker: str
    ruta: str
    qty: int
    tipo: TipoOrden
    precio: Optional[Decimal] = None   # STOPLMTP: stop = disparo, precio = límite
    stop: Optional[Decimal] = None
    tif: str = "DAY+"
    post_only: bool = False
    pref: Optional[str] = None
    proposito: Proposito = Proposito.DESCONOCIDA
    lote_id: Optional[str] = None
    nivel: Optional[Decimal] = None
    version: int = 0                # versión del objetivo del ticker (stops); el emisor descarta versiones viejas

    def __post_init__(self) -> None:
        """Injerto A §8.2: nada sale hacia DAS con acciones fraccionarias ni precios fuera del tick.

        `type(x) is int` rechaza `bool` y `float` a propósito (True es un int
        para `isinstance`); el token además debe caber en el int32 de DAS
        (manual L595-597).
        """
        if type(self.qty) is not int or self.qty <= 0:
            raise ValueError(f"qty debe ser int > 0, no {self.qty!r}")
        if type(self.token) is not int or not (-(2**31) <= self.token <= 2**31 - 1):
            raise ValueError(f"token fuera de int32: {self.token!r}")
        if self.tipo is TipoOrden.LIMITE and (self.precio is None or not en_tick(self.precio)):
            raise ValueError(f"límite fuera del tick: {self.precio}")
        if self.tipo is TipoOrden.STOP_LIMITE_PP:
            if self.stop is None or self.precio is None or not en_tick(self.stop) or not en_tick(self.precio):
                raise ValueError(f"STOPLMTP fuera del tick: stop={self.stop} límite={self.precio}")
            if self.lado is Lado.COMPRA and self.precio < self.stop:
                raise ValueError("compra STOPLMTP con límite por debajo del disparo")
            # L0-03: la simétrica para VENTA/CORTO (límite ≤ disparo); hoy el bot no la usa
            if self.lado in (Lado.VENTA, Lado.CORTO) and self.precio > self.stop:
                raise ValueError("venta STOPLMTP con límite por encima del disparo")
        if self.tipo is TipoOrden.LIMITE and self.stop is not None:
            raise ValueError("LMT no lleva disparo (stop)")   # L0-03: nada se ignora en silencio
        if self.tipo is TipoOrden.MERCADO and (self.precio is not None or self.stop is not None):
            raise ValueError("MKT no lleva precio")
        if self.post_only and self.tipo is not TipoOrden.LIMITE:
            raise ValueError("PostOnly solo con límite")


# ── mercado visto desde DAS (mercado_das.py) ───────────────────────────
@dataclass
class Cotizacion:
    ticker: str
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    bsz: Optional[int] = None
    asz: Optional[int] = None
    last: Optional[Decimal] = None
    volumen: Optional[int] = None
    vwap: Optional[Decimal] = None
    hi: Optional[Decimal] = None
    lo: Optional[Decimal] = None
    hora_servidor: Optional[str] = None
    actualizada_en: Optional[float] = None   # monotónico


@dataclass
class EstadoSimbolo:
    ticker: str
    ssr: Optional[bool] = None
    ta: Optional[str] = None
    tat: Optional[str] = None
    limit_down: Optional[Decimal] = None
    limit_up: Optional[Decimal] = None
    consultado_en: Optional[float] = None
    halt_desde: Optional[datetime] = None    # R-F-01
    k_halts_up: int = 0
    precio_parada: Optional[Decimal] = None
    orden_open_enviada: bool = False         # injerto A §8.23
    shortable: Optional[bool] = None
    tasa_corta: Optional[Decimal] = None
    reg_sho: Optional[bool] = None


# ── señal (fuente_senales.py) ──────────────────────────────────────────
@dataclass(frozen=True)
class Senal:
    clase: str                     # "evento" | "radar" | "hidratado" | "latido_feed" | "dia_nuevo"
    ticker: Optional[str]
    id: Optional[str]              # id = bot_alerts_cliente.id_evento(evento) (R-A-05)
    evento: Any = None             # bot_alerts_engine.Evento, tal cual (entrada_idx INCLUIDO: viaja picklado)
    momento: Any = None
    recibida_en: float = 0.0
    recuperada: bool = False
    estimacion: Optional[list] = None   # radar: filas de runner.estimacion_locates + "strategy_id" añadido por la fuente
    precio_radar: Optional[Decimal] = None
    feed: Optional[dict] = None         # latido_feed: {"ultima_vela_en": epoch, "vivo": bool}
    origen: str = "tuberia"        # "tuberia" | "proceso" | "grabacion"


# ── estado del ejecutor (decisor.py) ───────────────────────────────────
@dataclass
class Orden:                       # nuestra vista de una orden (token = clave; el id de DAS llega después)
    token: int
    ticker: str
    lado: Lado
    tipo: TipoOrden
    qty: int
    precio: Optional[Decimal]
    stop: Optional[Decimal]
    ruta: str
    proposito: Proposito
    lote_id: Optional[str]
    nivel: Optional[Decimal]
    origen: Origen
    id_das: Optional[int] = None
    estado: EstadoOrden = EstadoOrden.SENDING
    lvqty: int = 0
    llenas: int = 0
    cxlqty: int = 0
    tipo_das_crudo: Optional[str] = None
    enviada_en: float = 0.0
    ultima_act: float = 0.0
    notas: str = ""
    version: int = 0
    intentos: int = 0
    primer_intento_en: float = 0.0


@dataclass
class Fill:
    id_trade: int
    token: Optional[int]
    id_orden: Optional[int]
    ticker: str
    lado: str
    qty: int
    precio: Decimal
    ruta: str
    hora: str
    liq: Optional[str]
    ecn_fee: Optional[Decimal]
    simulado: bool = False


@dataclass
class Lote:                        # una estrategia dentro de un ticker (R-B-03: N lotes, una orden)
    id: str                        # = id_evento de la entrada: ticker|strategy_id|momento[:19]|entrada
    strategy_id: str
    estrategia: str
    ticker: str
    direccion: str
    pedidas: int
    llenas: int = 0
    precio_medio: Decimal = Decimal("0")
    nivel_stop: Optional[Decimal] = None
    riesgo_usd: Decimal = Decimal("0")
    estado: EstadoLote = EstadoLote.ABRIENDO
    reentrada_n: int = 0
    entrada_idx: Optional[int] = None
    nivel_piramide: Optional[int] = None
    hora_salida: Optional[str] = None
    eod: Optional[str] = None
    tp_pendiente: int = 0
    version_estrategia: str = ""   # R-E-03: hash de la definición con la que nació el lote


@dataclass
class IntentoEntrada:              # máquina de estados de R-B-01 v3 para UN ticker
    ticker: str
    lotes: list[str]
    qty_total: int
    bid_senal: Decimal
    ask_senal: Decimal
    precio_senal: Decimal
    t_cierre_vela: float
    t_limite: float
    fase: FaseIntento = FaseIntento.AGREGANDO
    token_agregar: Optional[int] = None
    token_cruce: Optional[int] = None
    llenas: int = 0
    canceladas: int = 0
    reintento_cruce: int = 0
    motivo_fin: Optional[str] = None
    cfg_congelada: Optional[dict] = None   # riesgo 18: el intento conserva la config con la que nació


@dataclass
class EstadoBS:                    # R-G-01 v4: `limite_stop` = el límite del stop que el precio pasó (L + 50 %)
    activado_en: float
    primer_stop: Decimal
    limite_stop: Decimal
    max_visto: Decimal
    informes: int = 0
    ultimo_informe: float = 0.0
    silenciado: bool = False
    perdido_realizado: Decimal = Decimal("0")


@dataclass
class PosicionTicker:
    ticker: str
    lotes: dict[str, Lote] = field(default_factory=dict)
    neta_fills: int = 0            # verdad INMEDIATA: suma signada de fills por token (corrección 2 del juez)
    neta_das: Optional[int] = None # lo último que dijo %POS / GET POSITIONS (reconciliación); None = no visto
    avg_das: Optional[Decimal] = None
    tipo_das: Optional[int] = None
    neta_das_en: Optional[float] = None
    estado: EstadoTicker = EstadoTicker.NORMAL
    motivo_estado: str = ""
    desde: Optional[float] = None
    bs: Optional[EstadoBS] = None
    intento: Optional[IntentoEntrada] = None
    senal_guardada_halt: Optional[Senal] = None                  # R-F-04 (b)
    sin_reentrada_hasta_sigue: bool = False                      # R-G-03, R-F-03
    intervencion_humana: bool = False                            # R-K-02 / R-M-03
    version_stops: int = 0                                       # injerto A §8.6: sube con cada fill; invalida REPLACE viejos
    descubierta_desde: Optional[float] = None
    persecuciones_ask: int = 0
    # R3-SAL-1: monotónico del ÚLTIMO fill aplicado en ESTE ticker (lo rellena el decisor). «Cerrar todo» solo se
    # fía de neta_das si el %POS llegó DESPUÉS (neta_das_en > ultimo_fill_en): si no, puede ir atrasado.
    ultimo_fill_en: Optional[float] = None
    # Jaume 29-sep: «/pausar X» → X no abre entradas nuevas (ni pirámides «add»); stops y salidas siguen. Lo levanta
    # «/sigue X» (o «/sigue» a secas). Persistido por el diario (registro «comando» pausar/sigue con args=[X]).
    pausado_por_humano: bool = False

    @property
    def neta(self) -> int:
        """La neta OPERATIVA: fills (inmediata). Si neta_das discrepa, la reconciliación manda un barrido antes de tocar los stops."""
        return self.neta_fills


@dataclass
class Locate:                      # R-H
    ticker: str
    strategy_id: str
    pedidas: int
    localizadas: int = 0
    precio_accion: Decimal = Decimal("0")
    coste: Decimal = Decimal("0")
    id_das: Optional[int] = None
    token: Optional[int] = None
    estado: str = "buscando"
    usadas: int = 0
    reutilizable: Optional[bool] = None
    comprado_en: Optional[float] = None
    ultimo_inquire_en: Optional[float] = None
    compras: int = 0
    # Jaume 29-sep (locates por FASES, `reglas.locates`): "A" radar sin señal · "B" intento único en la señal de
    # entrada · "C" dentro, faltan para las pirámides · "C_piramide" intento único en la señal de pirámide ·
    # "D" posición cerrada (sin consultas hasta la reentrada). `precio_senal`: la referencia de «a tiro».
    fase: str = "A"
    precio_senal: Optional[Decimal] = None
    # Decisión 47 (Jaume 30-sep): fase "P" = la entrada se perdió por locates y quedan pirámides «add»: se buscan
    # las acciones de las pirámides PENDIENTES ((k del nivel, acciones), sin las de la entrada perdida) y la
    # primera pirámide con locates entra SIN base con el nivel de stop de la entrada perdida (`stop_perdida`).
    # `senal_perdida` = id de esa entrada (tras la salida total del motor, su reentrada es legítima y la cuenta).
    stop_perdida: Optional[Decimal] = None
    senal_perdida: Optional[str] = None
    piramides_pendientes: tuple = ()


@dataclass
class Cuenta:
    bp: Optional[Decimal] = None
    bp_overnight: Optional[Decimal] = None
    equity: Optional[Decimal] = None
    htb_hoy: Decimal = Decimal("0")
    leida_en: Optional[float] = None
    bp_reservado: Decimal = Decimal("0")   # R-E-02


@dataclass
class EstadoBot:                   # TODO lo que el decisor sabe. Se reconstruye del diario + DAS al arrancar (H-2).
    fase: Fase
    dia: date
    vigilando: bool = True
    pausa_global: bool = False
    control_humano: bool = False
    senales_vistas: set[str] = field(default_factory=set)
    posiciones: dict[str, PosicionTicker] = field(default_factory=dict)
    ordenes: dict[int, Orden] = field(default_factory=dict)            # por token
    id_a_token: dict[int, int] = field(default_factory=dict)
    fills: dict[int, list[Fill]] = field(default_factory=dict)         # por token (libro de fills, verdad inmediata)
    ordenes_ajenas: dict[int, MsgOrden] = field(default_factory=dict)  # token no nuestro u orderSrc ≠ CMDAPI (R-K-02)
    locates: dict[tuple[str, str], Locate] = field(default_factory=dict)  # (ticker, strategy_id)
    gasto_locates_dia: Decimal = Decimal("0")                          # R-H-03
    locates_deshabilitados: bool = False                               # R-H-02
    cuenta: Cuenta = field(default_factory=Cuenta)
    das_conectado: bool = False
    das_logon: dict[str, Optional[bool]] = field(default_factory=dict)
    reconciliacion_ok_en: Optional[float] = None
    ultima_respuesta_barrido_en: Optional[float] = None
    feed_ultima_vela_en: Optional[float] = None
    modo_degradado: set[str] = field(default_factory=set)              # {"feed", "das", "reconciliacion", "disco"} (R-J-03 + corrección 4)
    ultimo_fill_en: Optional[float] = None
    config_version: int = 0
    ultimo_seq_token: int = 0
    rutas_habilitadas: dict[str, bool] = field(default_factory=dict)   # GET RouteStatus del primer día
    qty_corto_negativa: Optional[bool] = None                          # injerto A §8.8: se confirma el primer día
    # Jaume 29-sep: (ticker, strategy_id) → id de la PRIMERA señal principal del día que llegó a los locates (la
    # única oportunidad de entrada; las siguientes se pierden salvo reentrada legítima). Anotación «senal_principal».
    senales_principales: dict[tuple[str, str], str] = field(default_factory=dict)
    # Decisión 50 (Jaume 1-oct): la primera compra de locates que no cabe en el tope del día (o lo pagado lo alcanza)
    # corta las compras de locates de TODOS los tickers hasta el cambio de día. Anotación «locates_tope_global».
    locates_tope_dia: bool = False


# ── referencia de Massive y niveles de stop (ajuste (a) del orquestador) ─
@dataclass(frozen=True)
class Ficha:                       # /v3/reference/tickers/{t} (R-A-03 v2); la construye referencia_massive.py
    ticker: str
    list_date: Optional[date]
    sic_code: Optional[str]
    tipo: Optional[str]
    market_cap: Optional[Decimal]
    nombre: str


@dataclass(frozen=True)
class NivelesStop:                 # R-C-01 v4 (Jaume 29-sep, stop único): disparo EN L, límite L + 50 % SUMADO; `bajo_banda` = recortado bajo limit up (R-F-02)
    disparo: Decimal
    limite: Decimal
    bajo_banda: bool


@dataclass(frozen=True)
class StopDeseado:                 # una orden del conjunto deseado de stops (reglas/stops.conjunto_deseado)
    proposito: Proposito
    nivel: Decimal
    qty: int
    disparo: Decimal
    limite: Decimal


# ── acciones que devuelve el decisor (el ejecutor las EJECUTA en orden) ─
@dataclass(frozen=True)
class Accion:
    pass


@dataclass(frozen=True)
class EnviarOrden(Accion):
    orden: OrdenNueva
    serie: Optional[str] = None    # serie = f"stops:{ticker}" → el emisor descarta versión < vigente


@dataclass(frozen=True)
class Cancelar(Accion):
    id_das: int
    token: Optional[int]
    motivo: str


@dataclass(frozen=True)
class CancelarTicker(Accion):      # CANCEL ALLSYMB
    ticker: str
    motivo: str


@dataclass(frozen=True)
class Reemplazar(Accion):
    id_das: int
    token: int
    qty: int
    stop: Optional[Decimal]
    precio: Optional[Decimal]
    motivo: str
    version: int = 0
    serie: Optional[str] = None


@dataclass(frozen=True)
class InvalidarSerie(Accion):      # sube la versión vigente de una serie en el emisor (tras un fill de stop)
    serie: str
    version: int


@dataclass(frozen=True)
class Consultar(Accion):           # "GET BP", "GET SymStatus X", "GET LDLU X", "POSREFRESH", "SLReuseQuery X", ...
    comando: str


@dataclass(frozen=True)
class Suscribir(Accion):
    ticker: str
    alta: bool


@dataclass(frozen=True)
class LocateInquire(Accion):
    ticker: str
    qty: int
    ruta: str


@dataclass(frozen=True)
class LocateComprar(Accion):
    ticker: str
    qty: int
    ruta: str
    token: int


@dataclass(frozen=True)
class LocateOferta(Accion):
    id_das: int
    aceptar: bool


@dataclass(frozen=True)
class LocateCancelar(Accion):      # decisión 50 (Jaume 1-oct): «SLCANCELORDER id» de una compra Pending/Waiting
    id_das: int
    motivo: str = ""


@dataclass(frozen=True)
class Avisar(Accion):
    nivel: Nivel
    grupo: Grupo
    texto: str
    clave: Optional[str] = None


@dataclass(frozen=True)
class Anotar(Accion):
    tipo: str
    datos: dict


@dataclass(frozen=True)
class Programar(Accion):
    clave: str
    en_s: float
    datos: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Desprogramar(Accion):
    clave: str


@dataclass(frozen=True)
class PublicarFoto(Accion):        # estado/foto.json (panel 4.4)
    pass


@dataclass(frozen=True)
class PedirAlSupervisor(Accion):   # estado/orden_supervisor.jsonl: {"relanzar": "ejecutor"} (fallback del vigilante)
    peticion: str


@dataclass(frozen=True)
class Salir(Accion):               # el proceso termina con este código (reloj > 2 s, hash del motor, doble instancia)
    codigo: int
    motivo: str


# ── mensajes de la cola del ejecutor (todo entra por aquí) ─────────────
@dataclass(frozen=True)
class Mensaje:
    pass


@dataclass(frozen=True)
class SenalRecibida(Mensaje):
    senal: Senal


@dataclass(frozen=True)
class DeDAS(Mensaje):
    msg: MensajeDAS
    simulado: bool = False


@dataclass(frozen=True)
class Tic(Mensaje):
    pass


@dataclass(frozen=True)
class Temporizador(Mensaje):
    clave: str
    datos: dict


@dataclass(frozen=True)
class ComandoRecibido(Mensaje):
    comando: "Comando"


@dataclass(frozen=True)
class ConfigNueva(Mensaje):
    config: "Config"
    aviso: Optional[str]


@dataclass(frozen=True)
class ConexionDAS(Mensaje):
    conectado: bool
    motivo: str


@dataclass(frozen=True)
class HiloCaido(Mensaje):          # un hilo de borde murió y se relanzó (HiloVigilado)
    nombre: str
    error: str
    relanzado: bool


@dataclass(frozen=True)
class OrdenDescartada(Mensaje):    # D2a-06: el emisor purgó un NEWORDER por versión vieja de su serie
    """El emisor (cliente.py) avisa al decisor de cada NEWORDER que NO llegó a salir.

    Nada se purga en silencio: el decisor pasa la orden `token` a CLOSED con la
    nota «descartada por versión» y relanza en el acto el plan de stops del
    ticker. `ticker` es opcional (el decisor lo sabe por el token); se rellena
    cuando el emisor lo tiene a mano.
    """
    token: int
    serie: Optional[str] = None
    version: int = 0
    motivo: str = "descartada por versión"
    ticker: Optional[str] = None


# ── configuración (config.py la carga; el esquema es el de §7) ─────────
@dataclass(frozen=True)
class EstrategiaConfig:
    strategy_id: str
    name: str
    origen: str
    ejecutar: bool
    avisar_grupo_a: bool
    riesgo_usd: Decimal
    riesgos_piramide: list[Optional[Decimal]]
    riesgo_piramide_usd: Optional[Decimal]
    ev_pct: Decimal
    ev_rangos: list[dict]
    excluir_ipo: bool
    al_desactivar: str
    hora_fin_sesion: Optional[str]    # de definition (CM4)
    ventana_entradas: list[dict]
    hora_salida: Optional[str]
    accept_reentries: bool
    max_reentries: int
    niveles_piramide: list[dict]
    es_rth: bool
    definition_hash: str
    definition: dict
    sin_ev: bool = False    # Decisión 23 (Jaume 30-sep): ev_pct null en el cuadro → no ejecuta (ev_pct queda a 0) y avisa
    # Decisión 20 (Jaume 30-sep, PENDIENTE FUTURO): algún nivel de pirámide con repeticiones (`times` ≥ 2 o
    # ilimitado) → no ejecuta y avisa una vez al día, como `sin_ev`
    con_repeticiones: bool = False


@dataclass(frozen=True)
class Config:
    schema_version: int
    config_version: int
    sha256: str
    motor_hash: str
    estrategias_hash: str
    generado_at: str
    fase: Fase
    vigilando: bool
    horario: dict
    modo_seguridad: dict
    lista_negra: list[str]
    pausar_entradas: bool
    locates: dict
    entrada: dict
    salidas: dict
    stops: dict
    halts: dict
    exclusiones: dict
    rutas: dict
    tecnicos: dict
    alertas_grupo_a: dict
    estrategias: dict[str, EstrategiaConfig]
    cuenta_das: str                # nombre literal de la cuenta (SLAvailQuery lo exige); viene del .env, NO del fichero


@dataclass(frozen=True)
class Comando:                     # comandos.py
    nombre: str
    args: list[str]
    chat_id: int
    requiere: str
    id: str
    texto: str


@dataclass(frozen=True)
class Aviso:                       # avisos.py
    nivel: Nivel
    grupo: Grupo
    texto: str
    clave: Optional[str]
    creado_en: float


@dataclass(frozen=True)
class Registro:                    # diario.py
    v: int
    seq: int
    t: str
    proceso: str
    tipo: str
    datos: dict
