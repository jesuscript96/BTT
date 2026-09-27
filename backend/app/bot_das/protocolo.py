"""Protocolo CMD API de DAS Trader: formatear lo que enviamos y parsear lo que llega. PURO.

QUÉ HACE. Dos direcciones y ninguna red. Hacia DAS: `cmd_*` devuelven la
línea EXACTA del manual (`manual_2026.txt`, rev. 2025-07-31) para cada
comando que usa el bot (LOGIN, NEWORDER, CANCEL, REPLACE, GET, SB, locates,
QUIT), con `formatear_precio` como ÚNICA salida de precios. Desde DAS:
`Parser.parsear` convierte cada línea cruda en una dataclass de `tipos`
(`MsgOrden`, `MsgOrderAct`, `MsgTrade`, `MsgPos`, `MsgQuote`, …) resolviendo
las 29 ambigüedades de la especificación §5 (campos opcionales, `Type` con
espacios, `notes` vacías, `Buy`/`Shrt`, `$IssueStatus`/`$SymStatus`,
`SLRouteMinChargeRet` con y sin `$`, `$INTMSG` multilínea, las 12 líneas de
conexión con espacio). `es_mutante` es el candado de la fase sombra (R-O-03) y
`redactar` tapa la clave del LOGIN antes de que nada se registre (R-Q-01).

POR QUÉ ESTÁ AQUÍ. `cliente.py` (socket) y `simulador_das.py` (DAS falso)
hablan el mismo protocolo; al vivir en un módulo puro se prueba con tablas de
líneas crudas (`fixtures/lineas_das.txt`) y con un fuzz de miles de líneas sin
abrir un socket. El decisor nunca ve texto: ve dataclasses con `Decimal` e
`int`, y la línea `cruda` conservada para el diario.

LAS TRAMPAS.
  * `%ORDER` puede traer el campo `Type` con VARIAS palabras («SLP: 2.97
    2.99», captura del socio, libro 2g.3): un `split()` por posiciones lee la
    cantidad en el sitio del precio SIN dar error (riesgo 1). Por eso el parser
    ancla desde la DERECHA: busca el par `estado` (conjunto cerrado de 9
    valores) + `hora` (`HH:MM:SS`) y cuenta hacia atrás `qty lvqty cxlqty
    precio ruta`; el `Type` es todo lo que queda entre `b/s` y `qty`.
  * Un número al final de `notes` parece un token (riesgo 2): solo se acepta
    si `es_nuestro(token)` (esquema + día de hoy); si no, va a `notas` y la
    orden se cruza por `id_das`.
  * `notes` vacías dejan DOS espacios (manual L934-936, L1710): `split()`
    los colapsa y desplaza el token; aquí se parte con `split(" ", n)` sin
    colapsar donde hay texto libre (%OrderAct, %SLRET, %SLOrder).
  * `%ITRADE` NO es `%TRADE` con otro nombre: la cuenta va primero y el
    trader al final (manual L1447-1454). Rama propia.
  * `$Quote` es un PARCHE (manual L1268-1269): solo trae las claves que
    cambiaron. El parser devuelve solo las presentes, sin convertir, y
    conserva las desconocidas (`RVOL`, `tradesAllDay`); `mercado_das` aplica
    el parche sobre su libro.
  * El signo de `Quantity` en cortos no está documentado (§5.12):
    `normalizar_pos` usa `abs()` y el `Type == 3` para dar la neta SIGNADA;
    vale con signo positivo o negativo.
  * `parsear` NUNCA lanza: lo que no cuadra es `MsgDesconocido` con la línea
    cruda dentro (frontera de mensaje). Un precio no numérico en un `%ORDER`
    o `%OrderAct` de una orden MKT («just for reference for non limit orders»,
    L475-477) se lee como 0 en vez de perder la orden entera.
  * `formatear_precio` LANZA (`PrecioFueraDeTick`) si el precio no está al
    tick (injerto A §8.1): DAS recibe «10.3» o nada, nunca «10.299999».
  * Las palabras clave se comparan sin distinguir mayúsculas (la prueba
    oficial del manual usa `login`, L2037); las RESPUESTAS llegan con la
    capitalización mostrada y así se conservan en los campos.
  * `%SLRET` lleva `Notes` con espacios y `Account` opcional al final
    (L1707-1718): sin conocer la cuenta es imposible distinguir «Not enough
    shares» de «Not enough» + cuenta «shares». El `Parser` admite `cuenta`
    (la del LOGIN) y entonces la separación es exacta; sin ella aplica una
    heurística documentada en `_notas_y_cuenta`.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

from app.bot_das.tipos import (
    EstadoOrden,
    Lado,
    MensajeDAS,
    MsgAccountInfo,
    MsgBar,
    MsgBP,
    MsgConexion,
    MsgDesconocido,
    MsgInformativo,
    MsgIntMsg,
    MsgIssueStatus,
    MsgLDLU,
    MsgMarcador,
    MsgOrden,
    MsgOrderAct,
    MsgPos,
    MsgQuote,
    MsgRouteStatus,
    MsgShortInfo,
    MsgSLAvail,
    MsgSLMinCharge,
    MsgSLOrder,
    MsgSLRet,
    MsgSLReuse,
    MsgStInfoEx,
    MsgTrade,
    MsgTS,
    OrdenNueva,
    TipoOrden,
    en_tick,
)

# ── transporte (§5.1: no documentado; se envía \r\n y al leer se acepta \n y se descarta \r) ──
FIN_LINEA = "\r\n"
CODIFICACION = "latin-1"           # decode(errors="replace"): las notas del bróker pueden traer no-ASCII

# ── candado de la fase sombra (R-O-03): ningún comando de esta lista sale en sombra ──
MUTANTES = frozenset({
    "NEWORDER", "CANCEL", "REPLACE", "COMPLEXORDER", "SCRIPT", "GSCRIPT",
    "SLNEWORDER", "SLOFFEROPERATION", "SLCANCELORDER",
})
_RUTA_INQUIRE_MUTANTE = "ALLROUTE"   # §5.22: SLPRICEINQUIRE … ALLROUTE crea órdenes Offered en rutas tipo 1

# ── conjuntos cerrados del manual ──
ESTADOS_ORDEN = frozenset(e.value for e in EstadoOrden if e is not EstadoOrden.DESCONOCIDO)   # L379-405
ACCIONES_ORDERACT = frozenset({                                                             # L443-458
    "Sending", "Send_Rej", "Accept", "Canceling", "Canceled", "CancelRej",
    "TimeOut", "Execute", "Close", "Replaced", "Replacing", "ReplaceRej",
})
ESTADOS_LOCATE = frozenset({                                                                # L1778-1793
    "Pending", "Waiting", "Located", "Offered", "Canceled", "Rejected", "Closed", "Declined",
})
# Las 12 líneas de L1472-1490 → (servidor, evento). Dos llevan espacio: se comparan ENTERAS (§5.26).
CONEXION_LITERALES: dict[str, tuple[str, str]] = {
    "#OrderServer:Logon:Successful": ("OrderServer", "Logon:Successful"),
    "#OrderServer:Logon:Failed": ("OrderServer", "Logon:Failed"),
    "#OrderServer:Connect:Successful": ("OrderServer", "Connect:Successful"),
    "#OrderServer:Connect:Failed": ("OrderServer", "Connect:Failed"),
    "#QuoteServer:Logon:Successful": ("QuoteServer", "Logon:Successful"),
    "#QuoteServer:Logon:Failed": ("QuoteServer", "Logon:Failed"),
    "#QuoteServer:Connect:Successful": ("QuoteServer", "Connect:Successful"),
    "#QuoteServer:Connect:Failed": ("QuoteServer", "Connect:Failed"),
    "#QuoteServer:Missing heartbeat": ("QuoteServer", "Missing heartbeat"),
    "#OrderServer:Missing heartbeat": ("OrderServer", "Missing heartbeat"),
    "#QuoteServer:Lost Connection": ("QuoteServer", "Lost Connection"),
    "#OrderServer:Lost Connection": ("OrderServer", "Lost Connection"),
}
_CONEXION_INSENSIBLE = {clave.lower(): valor for clave, valor in CONEXION_LITERALES.items()}
# §5.5: %OrderAct trae `Buy`/`Shrt`; %ORDER/%TRADE traen B/S/SS. Todo se normaliza a B/S/SS.
LADOS = {"B": "B", "BUY": "B", "S": "S", "SELL": "S", "SS": "SS", "SHRT": "SS", "SHORT": "SS"}
# Marcadores de volcado (L257-276, L332-346, L496-507, L999, L1752-1765): se ignora lo que siga a la palabra (§5.13-14).
MARCADORES = {
    "#POS": "#POS", "#POSEND": "#POSEND", "#ORDER": "#Order", "#ORDEREND": "#OrderEnd",
    "#TRADE": "#Trade", "#TRADEEND": "#TradeEnd", "#SLORDER": "#SLOrder", "#SLORDEREND": "#SLOrderEnd",
    "#BUYINGPOWER": "#buyingpower",
}
_BLOQUE_POR_MARCADOR: dict[str, tuple[bool, Optional[str]]] = {   # (cambia el bloque, bloque nuevo)
    "#POS": (True, "POS"), "#POSEND": (True, None), "#Order": (True, "Order"), "#OrderEnd": (True, None),
    "#Trade": (True, "Trade"), "#TradeEnd": (True, None), "#SLOrder": (True, "SLOrder"), "#SLOrderEnd": (True, None),
    "#buyingpower": (False, None),
}
_INFORMATIVOS = frozenset({"ECHO", "CLIENT", "$TOPLST", "$LV2"})   # §5.25, L1361-1370, L1536-1557

# ── GET: conjunto CERRADO de nombres (§4.1). Se admiten en cualquier capitalización y salen con la del manual ──
GET_CON_ARGUMENTO_OBLIGATORIO = ("SHORTINFO",)                 # L1005-1010
GET_CON_ARGUMENTO_OPCIONAL = ("LDLU", "SymStatus")             # §5.8: el símbolo es una presunción (comprobar_das paso 2)
GET_SIN_ARGUMENTO = ("BP", "AccountInfo", "POSITIONS", "ORDERS", "TRADES", "LOCATES", "RouteStatus", "INTMSGS")
COMANDOS_SUELTOS = ("POSREFRESH", "ECHO", "CLIENT")             # L326-330, L1459-1471
CANALES_SB = ("Lv1", "tms", "Lv2")                             # L1172-1247 (DAYCHART/MINCHART/TopList no se usan, R-A-06)
_NOMBRES_GET = {n.upper(): n for n in GET_CON_ARGUMENTO_OBLIGATORIO + GET_CON_ARGUMENTO_OPCIONAL + GET_SIN_ARGUMENTO}
_NOMBRES_SUELTOS = {n.upper(): n for n in COMANDOS_SUELTOS}
_CANALES = {c.upper(): c for c in CANALES_SB}

_RE_HORA = re.compile(r"\d{2}:\d{2}:\d{2}")
_RE_ENTERO = re.compile(r"[+-]?\d+")
_RE_STINFOEX = re.compile(r"(\w+):\s*([\d.]+)%")                # §5.21: tolerante (ConcShr vs ConcShrt)
_RE_LOGIN = re.compile(r"((?<!\S)login[ \t]+\S+[ \t]+)(\S+)", re.IGNORECASE)
_RE_TOKEN_TELEGRAM = re.compile(r"bot\d+:[A-Za-z0-9_-]+", re.IGNORECASE)
_RE_TOKEN_TELEGRAM_SUELTO = re.compile(r"(?<![\w*])\d{5,}:[A-Za-z0-9_-]{30,}")   # forma real: 8-10 dígitos + «:» + 35 caracteres
_MAX_INT32 = 2**31 - 1
_MIN_INT32 = -(2**31)


class PrecioFueraDeTick(ValueError):
    """El precio no es múltiplo de su tick (o no es un Decimal finito > 0): NO sale al socket (injerto A §8.1)."""


# ══════════════════════════════════════════════════════════════════════
# Hacia DAS
# ══════════════════════════════════════════════════════════════════════
def formatear_precio(p: Decimal) -> str:
    """ÚNICA salida de precios al socket (injerto A §8.1, §5.28). LANZA `PrecioFueraDeTick` si `not en_tick(p)`.

    Sin notación científica y sin ceros de más: Decimal("10.30") → "10.3",
    Decimal("3.00") → "3", Decimal("0.1234") → "0.1234". Solo acepta
    `Decimal` (un float aquí es un error de programación, no un precio).
    """
    if not isinstance(p, Decimal):
        raise PrecioFueraDeTick(f"el precio debe ser Decimal, no {type(p).__name__}: {p!r}")
    if not en_tick(p):
        raise PrecioFueraDeTick(f"precio fuera del tick: {p}")
    return format(p.normalize(), "f")


def es_mutante(linea: str) -> bool:
    """True si la línea cambia algo en DAS (R-O-03: la sombra lo prohíbe a nivel de código).

    Primera palabra ∈ MUTANTES, sin distinguir mayúsculas ni espacios
    delante; además «SLPRICEINQUIRE … ALLROUTE» (§5.22: en rutas tipo 1 la
    consulta ya crea una orden de locate `Offered`), pero NO ALLROUTEWTTYPE1.
    Trampa (riesgo 10): una línea con un salto de línea DENTRO llevaría dos
    comandos al socket; basta con que uno de los trozos sea mutante.
    """
    if not isinstance(linea, str):
        raise TypeError(f"es_mutante espera una línea de texto, no {type(linea).__name__}")
    # Una «línea» con un salto dentro son DOS comandos para DAS («GET BP\r\nNEWORDER …»):
    # se mira cada trozo (splitlines corta también en \v, \f, \x1c…, más conservador que \r\n).
    return any(_trozo_mutante(trozo) for trozo in linea.splitlines())


def _trozo_mutante(trozo: str) -> bool:
    partes = trozo.split()
    if not partes:
        return False
    primera = partes[0].upper()
    if primera in MUTANTES:
        return True
    if primera == "SLPRICEINQUIRE":
        return any(p.upper() == _RUTA_INQUIRE_MUTANTE for p in partes[1:])
    return False


def cmd_login(usuario: str, clave: str, cuenta: str, watch: bool) -> str:
    """«LOGIN Trader Password Account 1/0» (L243-251): 1 = watch (vigilante), 0 = normal (ejecutor)."""
    return (f"LOGIN {_palabra('usuario', usuario)} {_palabra('clave', clave)} "
            f"{_palabra('cuenta', cuenta)} {1 if watch else 0}")


def cmd_neworder(o: OrdenNueva) -> str:
    """Literales del manual para los tres tipos que usa el bot.

    LMT:      «NEWORDER token b/s symbol route share price [PostOnly] TIF=…»   (L543-547, L767-770, L709-728)
    MKT:      «NEWORDER token b/s symbol route share MKT TIF=…»                (L549-553)
    STOPLMTP: «NEWORDER token b/s symbol route share STOPLMTP StopPrice Price TIF=…» (L618-624)
    `Pref=…` (L794-801) se añade al final si la orden lo lleva. Los precios
    salen por `formatear_precio` (lanza fuera de tick); `OrdenNueva` ya validó
    qty, token y ticks en su constructor (injerto A §8.2).
    """
    if not isinstance(o, OrdenNueva):
        raise TypeError(f"cmd_neworder espera una OrdenNueva, no {type(o).__name__}")
    lado = Lado(o.lado).value          # ValueError con un lado que no sea B/S/SS (nunca «Buy» ni texto libre)
    cabeza = (f"NEWORDER {_token('token', o.token)} {lado} {_palabra('ticker', o.ticker)} "
              f"{_palabra('ruta', o.ruta)} {_entero_positivo('qty', o.qty)}")
    tif = _palabra("tif", o.tif)
    if o.tipo is TipoOrden.LIMITE:
        cuerpo = formatear_precio(o.precio) + (" PostOnly" if o.post_only else "")
    elif o.tipo is TipoOrden.MERCADO:
        cuerpo = "MKT"
    elif o.tipo is TipoOrden.STOP_LIMITE_PP:
        cuerpo = f"STOPLMTP {formatear_precio(o.stop)} {formatear_precio(o.precio)}"
    else:
        raise ValueError(f"tipo de orden no admitido: {o.tipo!r}")
    linea = f"{cabeza} {cuerpo} TIF={tif}"
    if o.pref:
        linea += f" Pref={_palabra('pref', o.pref)}"
    return linea


def cmd_cancel(id_das: int) -> str:
    """«CANCEL orderid» (L802-803): el id lo generó DAS (`%ORDER`), nunca el token."""
    return f"CANCEL {_entero_positivo('id_das', id_das)}"


def cmd_cancel_all() -> str:
    """«CANCEL ALL» (L804-805): solo `/cerrar_todo SI`."""
    return "CANCEL ALL"


def cmd_cancel_allsymb(ticker: str) -> str:
    """«CANCEL ALLSYMB ticker» (L226-229, L806-810): limpieza R-C-11 con neta 0, cierre de lote, halt."""
    return f"CANCEL ALLSYMB {_palabra('ticker', ticker)}"


def cmd_replace(id_das: int, qty: int, tipo: TipoOrden, precio: Optional[Decimal], stop: Optional[Decimal]) -> str:
    """«REPLACE orderid share price» (L822-828) / «REPLACE orderid share STOPLMT StopPrice Price» (L850-854).

    STOPLMTP no aparece en la lista de REPLACE del manual (§5.6): se envía la
    forma STOPLMT y el decisor comprueba después en `%ORDER` que el tipo sigue
    siendo el de pre/post (`tipo_conserva_pp` + `replace_verificar`, 2h.8).
    MKT («REPLACE orderid share MKT», L831-834) se admite por completitud
    del manual aunque el bot no lo use. Los precios salen por
    `formatear_precio` (lanza fuera de tick, riesgo 12).
    """
    if not isinstance(tipo, TipoOrden):
        raise ValueError(f"tipo de orden no admitido: {tipo!r}")
    cabeza = f"REPLACE {_entero_positivo('id_das', id_das)} {_entero_positivo('qty', qty)}"
    if tipo is TipoOrden.LIMITE:
        if precio is None or stop is not None:
            raise ValueError("REPLACE de una límite lleva precio y no lleva stop")
        return f"{cabeza} {formatear_precio(precio)}"
    if tipo is TipoOrden.STOP_LIMITE_PP:
        if precio is None or stop is None:
            raise ValueError("REPLACE de un STOPLMTP lleva disparo y límite")
        return f"{cabeza} STOPLMT {formatear_precio(stop)} {formatear_precio(precio)}"
    if tipo is TipoOrden.MERCADO:
        if precio is not None or stop is not None:
            raise ValueError("REPLACE a mercado no lleva precios")
        return f"{cabeza} MKT"
    raise ValueError(f"tipo de orden no admitido: {tipo!r}")


def cmd_get(nombre: str, arg: Optional[str] = None) -> str:
    """«GET X [símbolo]» con un conjunto CERRADO de nombres (§4.1); si no, ValueError.

    Con argumento obligatorio: SHORTINFO (L1007). Opcional (§5.8, presunción):
    LDLU, SymStatus. Sin argumento: BP, AccountInfo, POSITIONS, ORDERS,
    TRADES, LOCATES, RouteStatus, INTMSGS. Sueltos (sin «GET»): POSREFRESH,
    ECHO [ON|OFF], CLIENT. El nombre se admite en cualquier capitalización y
    sale con la del manual.
    """
    if not isinstance(nombre, str):
        raise ValueError(f"nombre de GET debe ser texto: {nombre!r}")
    clave = nombre.strip().upper()
    if clave in _NOMBRES_SUELTOS:
        canonico = _NOMBRES_SUELTOS[clave]
        if arg is None:
            return canonico
        if canonico == "ECHO" and isinstance(arg, str) and arg.strip().upper() in ("ON", "OFF"):
            return f"ECHO {arg.strip().upper()}"
        raise ValueError(f"{canonico} no admite argumento: {arg!r}")
    if clave not in _NOMBRES_GET:
        raise ValueError(f"GET desconocido: {nombre!r} (admitidos: "
                         f"{', '.join(GET_CON_ARGUMENTO_OBLIGATORIO + GET_CON_ARGUMENTO_OPCIONAL + GET_SIN_ARGUMENTO)})")
    canonico = _NOMBRES_GET[clave]
    if canonico in GET_CON_ARGUMENTO_OBLIGATORIO and arg is None:
        raise ValueError(f"GET {canonico} exige un símbolo")
    if canonico in GET_SIN_ARGUMENTO and arg is not None:
        raise ValueError(f"GET {canonico} no admite argumento: {arg!r}")
    if arg is None:
        return f"GET {canonico}"
    return f"GET {canonico} {_palabra('símbolo', arg)}"


def cmd_sb(ticker: str, canal: str = "Lv1") -> str:
    """«SB Symbol Lv1» (L1173): el bot solo suscribe Lv1 (≤ 100 símbolos, L1985-1987); tms/Lv2 admitidos por el manual."""
    return f"SB {_palabra('ticker', ticker)} {_canal(canal)}"


def cmd_unsb(ticker: str, canal: str = "Lv1") -> str:
    """«UNSB Symbol Lv1» (L1238)."""
    return f"UNSB {_palabra('ticker', ticker)} {_canal(canal)}"


def cmd_return_full_lv1(si: bool) -> str:
    """«ReturnFullLv1 YES|NO» (L1529-1534): el bot manda NO (parche incremental que aplica `mercado_das`)."""
    return f"ReturnFullLv1 {'YES' if si else 'NO'}"


def cmd_sl_inquire(ticker: str, qty: int, ruta: str) -> str:
    """«SLPRICEINQUIRE Symbol LocateShares Route|ALLROUTE|ALLROUTEWTTYPE1» (L1648-1653). El bot usa ALLROUTEWTTYPE1 (§5.22)."""
    return f"SLPRICEINQUIRE {_palabra('ticker', ticker)} {_entero_positivo('qty', qty)} {_palabra('ruta', ruta)}"


def cmd_sl_neworder(ticker: str, qty: int, ruta: str, token: int) -> str:
    """«SLNEWORDER Symbol LocateShares Route token» (L1671-1677); tokens de `Origen.EJECUTOR_LOCATE`."""
    return (f"SLNEWORDER {_palabra('ticker', ticker)} {_entero_positivo('qty', qty)} "
            f"{_palabra('ruta', ruta)} {_token('token', token)}")


def cmd_sl_offer(id_das: int, aceptar: bool) -> str:
    """«SLOFFEROPERATION locateOrderId Accept|Reject» (L1692-1697): rutas de locate tipo 1."""
    return f"SLOFFEROPERATION {_entero_positivo('id_das', id_das)} {'Accept' if aceptar else 'Reject'}"


def cmd_sl_cancel(id_das: int) -> str:
    """«SLCANCELORDER locateOrderId» (L1686-1688): hora límite de intentos (rutas tipo 0)."""
    return f"SLCANCELORDER {_entero_positivo('id_das', id_das)}"


def cmd_sl_reuse(ticker: str) -> str:
    """«SLReuseQuery Symbol/ALL» (L1810-1811): EP-9, se consulta al comprar y tras cada reentrada."""
    return f"SLReuseQuery {_palabra('ticker', ticker)}"


def cmd_sl_avail(cuenta: str, ticker: str) -> str:
    """«SLAvailQuery Account Symbol» (L1796-1797): exige la cuenta literal (§5.23, `Config.cuenta_das`)."""
    return f"SLAvailQuery {_palabra('cuenta', cuenta)} {_palabra('ticker', ticker)}"


def cmd_sl_min_charge(ruta: str) -> str:
    """«SLRouteMinCharge RouteName/ALLROUTE» (L1823-1827): el mínimo por ruta entra en el EV (R-H-05)."""
    return f"SLRouteMinCharge {_palabra('ruta', ruta)}"


def cmd_quit() -> str:
    """«QUIT» (L1619-1621)."""
    return "QUIT"


# ══════════════════════════════════════════════════════════════════════
# Desde DAS
# ══════════════════════════════════════════════════════════════════════
class Parser:
    """Convierte líneas crudas en dataclasses de `tipos`. Estado SOLO para `$INTMSG` (multilínea) y los bloques `#…`/`#…End`.

    `es_nuestro(token) -> bool` decide si un entero es un token del bot
    (riesgo 2); `watch=True` marca como watch todo `%ORDER/%POS/%TRADE` que
    llegue por esa conexión (además de los `%I…`, que lo son siempre);
    `cuenta` es el nombre de la cuenta del LOGIN y hace exacta la separación
    `Notes`/`Account` de `%SLRET` (§5.4).
    """

    def __init__(self, es_nuestro: Callable[[int], bool], watch: bool = False, cuenta: Optional[str] = None) -> None:
        if not callable(es_nuestro):
            raise TypeError("es_nuestro debe ser una función token -> bool")
        self._es_nuestro = es_nuestro
        self._watch = bool(watch)
        self._cuenta = cuenta.strip() if isinstance(cuenta, str) and cuenta.strip() else None
        self._bloque: Optional[str] = None
        self._intmsg: dict[str, str] = {}

    @property
    def en_bloque(self) -> Optional[str]:
        """"POS" | "Order" | "Trade" | "SLOrder" | None (§5.11: los marcadores son opcionales)."""
        return self._bloque

    @property
    def es_nuestro(self) -> Callable[[int], bool]:
        return self._es_nuestro

    @property
    def watch(self) -> bool:
        return self._watch

    @property
    def cuenta(self) -> Optional[str]:
        return self._cuenta

    def parsear(self, linea: str) -> MensajeDAS:
        """NUNCA lanza (§5.15, frontera de mensaje); lo que no entiende → `MsgDesconocido` con la `cruda` dentro.

        La palabra clave se compara sin distinguir mayúsculas; `bytes` se
        decodifican en latin-1 con `errors="replace"` (§5.1); se quitan los
        `\\r`/`\\n` finales y la línea se conserva así en `cruda`.
        """
        cruda = ""
        try:
            if isinstance(linea, (bytes, bytearray)):
                linea = bytes(linea).decode(CODIFICACION, errors="replace")
            elif not isinstance(linea, str):
                linea = str(linea)
            cruda = linea.rstrip("\r\n")
            return self._despachar(cruda)
        except Exception:  # noqa: BLE001 — frontera de mensaje (§5.15): una línea rara jamás tumba el lector; queda como MsgDesconocido con la cruda
            return MsgDesconocido(cruda=cruda, palabra=_primera_palabra(cruda))

    # ── despacho ──────────────────────────────────────────────────────
    def _despachar(self, cruda: str) -> MensajeDAS:
        texto = cruda.strip()
        if not texto:
            return MsgDesconocido(cruda=cruda, palabra="")
        conexion = CONEXION_LITERALES.get(texto) or _CONEXION_INSENSIBLE.get(texto.lower())
        if conexion is not None:
            return MsgConexion(cruda=cruda, servidor=conexion[0], evento=conexion[1])
        palabra = texto.split(None, 1)[0]
        clave = palabra.upper()
        manejador = _MANEJADORES.get(clave)
        if manejador is not None:
            return manejador(self, cruda, texto)
        if clave in MARCADORES:
            return self._marcador(cruda, MARCADORES[clave])
        if clave.startswith("#") or clave in _INFORMATIVOS:
            return MsgInformativo(cruda=cruda, palabra=palabra)
        return MsgDesconocido(cruda=cruda, palabra=palabra)

    def _marcador(self, cruda: str, nombre: str) -> MsgMarcador:
        cambia, bloque = _BLOQUE_POR_MARCADOR[nombre]
        if cambia:
            self._bloque = bloque
        return MsgMarcador(cruda=cruda, nombre=nombre)

    def _nuestro(self, token: int) -> bool:
        try:
            return bool(self._es_nuestro(token))
        except Exception:  # noqa: BLE001 — frontera de callback: un `es_nuestro` roto no puede tumbar el parser; el token se trata como ajeno
            return False

    # ── órdenes ───────────────────────────────────────────────────────
    def _orden(self, cruda: str, texto: str, watch: bool = False) -> MensajeDAS:
        """%ORDER / %IORDER (L343-405, L930-932; §5.2 y §5.3): anclado desde la DERECHA por estado + hora (riesgo 1).

        Se buscan, de derecha a izquierda, las posiciones `k` con
        `c[k] ∈ ESTADOS_ORDEN`, `c[k+1]` = `HH:MM:SS` y las tres palabras
        `qty lvqty cxlqty` enteras delante; se prefiere la que deja
        detrás EXACTAMENTE 3 (15 campos) o 6 (19 campos) palabras, y si no hay
        ninguna así, la más a la derecha que deje al menos 3 (tolerante a un
        servidor que añada campos). Delante del estado: `qty lvqty cxlqty
        price route`; `tipo` = lo que queda entre `b/s` y `qty` (≥ 1 palabra).
        """
        c = texto.split()
        n = len(c)
        candidatos = [k for k in range(n - 2, 10, -1)   # k ≥ 11: id token symb b/s + ≥ 1 palabra de tipo + qty lvqty cxlqty price route
                      if c[k] in ESTADOS_ORDEN and _RE_HORA.fullmatch(c[k + 1]) and n - (k + 2) >= 3
                      and all(_RE_ENTERO.fullmatch(x) for x in c[k - 5:k - 2])]   # qty lvqty cxlqty son enteros
        if not candidatos:                       # origoid cuenta trader son obligatorios en las dos variantes (15 y 19)
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        exactos = [k for k in candidatos if n - (k + 2) in (3, 6)]
        j = exactos[0] if exactos else candidatos[0]
        resto = c[j + 2:]
        token_crudo = _entero_o_none(c[2])
        token = token_crudo if (token_crudo is not None and self._nuestro(token_crudo)) else None
        return MsgOrden(
            cruda=cruda, id=_entero(c[1]), token=token, ticker=c[3], lado=_lado(c[4]), tipo=" ".join(c[5:j - 5]),
            qty=_entero(c[j - 5]), lvqty=_entero(c[j - 4]), cxlqty=_entero(c[j - 3]), precio=_decimal_o_cero(c[j - 2]),
            ruta=c[j - 1], estado=EstadoOrden(c[j]), hora=c[j + 1], origoid=_entero(resto[0]), cuenta=resto[1],
            trader=resto[2], order_src=resto[3] if len(resto) > 3 else None, tif=resto[4] if len(resto) > 4 else None,
            pref=resto[5] if len(resto) > 5 else None, watch=watch or self._watch,
        )

    def _iorden(self, cruda: str, texto: str) -> MensajeDAS:
        return self._orden(cruda, texto, watch=True)

    def _orderact(self, cruda: str, texto: str) -> MensajeDAS:
        """%OrderAct id ActionType B/S symbol qty price route time notes token (L434-494, L934-944; §5.3-5.5).

        Tras la palabra clave, `split(" ", 8)` SIN colapsar: 8 campos fijos y
        el resto «notes token» intacto (notas vacías = dos espacios, L936).
        La última palabra del resto es el token solo si es entera Y
        `es_nuestro` (riesgo 2); si no, todo va a `notas`. Lado `Buy`/`Shrt`
        normalizado por `LADOS`; la acción se conserva tal cual (aunque no esté
        en `ACCIONES_ORDERACT`: la registra el decisor). El precio no numérico
        («just for reference», L475-477) se lee como 0.
        """
        _palabra_clave, _separador, cuerpo = texto.partition(" ")
        p = cuerpo.split(" ", 8)
        if len(p) < 8:
            return MsgDesconocido(cruda=cruda, palabra=_palabra_clave)
        notas, token = self._notas_y_token(p[8] if len(p) > 8 else "")
        return MsgOrderAct(
            cruda=cruda, id=_entero(p[0]), accion=p[1], lado=_lado(p[2]), ticker=p[3], qty=_entero(p[4]),
            precio=_decimal_o_cero(p[5]), ruta=p[6], hora=p[7], notas=notas, token=token,
        )

    def _notas_y_token(self, resto: str) -> tuple[str, Optional[int]]:
        """«notes token» (§5.4): última palabra entera Y nuestra → token; si no, todo va a notas (riesgo 2)."""
        if not resto.strip():
            return "", None
        cabeza, separador, ultimo = resto.rpartition(" ")
        if not separador:
            cabeza, ultimo = "", resto
        token = _entero_o_none(ultimo)
        if token is not None and self._nuestro(token):
            return cabeza.strip(), token
        return resto.strip(), None

    # ── ejecuciones ───────────────────────────────────────────────────
    def _trade(self, cruda: str, texto: str) -> MensajeDAS:
        """%TRADE id symb b/s qty price route time orderid [Liq EcnFee PL] (L495-539; §5.3).

        8 u 11 campos. Los opcionales NUNCA hacen perder el fill: un `EcnFee`
        o `PL` no numérico queda en None (la ejecución es la verdad inmediata
        del libro de fills, riesgo 8); los obligatorios sí se validan.
        """
        c = texto.split()
        if len(c) < 9:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgTrade(
            cruda=cruda, id=_entero(c[1]), ticker=c[2], lado=_lado(c[3]), qty=_entero(c[4]), precio=_decimal(c[5]),
            ruta=c[6], hora=c[7], id_orden=_entero(c[8]), liq=c[9] if len(c) > 9 else None,
            ecn_fee=_decimal_o_none(c[10]) if len(c) > 10 else None, pl=_decimal_o_none(c[11]) if len(c) > 11 else None,
            cuenta=None, trader=None, watch=self._watch,
        )

    def _itrade(self, cruda: str, texto: str) -> MensajeDAS:
        """%ITRADE (L1446-1458): OTRO orden de campos: Account tradeID symbol Side TradeShares TradePrice route exeTime orderID Trader."""
        c = texto.split()
        if len(c) < 10:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgTrade(
            cruda=cruda, id=_entero(c[2]), ticker=c[3], lado=_lado(c[4]), qty=_entero(c[5]), precio=_decimal(c[6]),
            ruta=c[7], hora=c[8], id_orden=_entero(c[9]), liq=None, ecn_fee=None, pl=None, cuenta=c[1],
            trader=c[10] if len(c) > 10 else None, watch=True,
        )

    # ── posiciones ────────────────────────────────────────────────────
    def _pos(self, cruda: str, texto: str, watch: bool = False) -> MensajeDAS:
        """%POS / %IPOS (L256-323): 8 o 9 campos (`Unrealized` opcional); neta signada por `normalizar_pos`."""
        c = texto.split()
        if len(c) < 9:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        tipo = _entero(c[2])
        qty_cruda = _entero(c[3])
        return MsgPos(
            cruda=cruda, ticker=c[1], tipo=tipo, qty_cruda=qty_cruda, neta=normalizar_pos(c[1], tipo, qty_cruda, None),
            avg=_decimal(c[4]), init_qty=_entero(c[5]), init_precio=_decimal(c[6]), realizado=_decimal(c[7]),
            creada=c[8], no_realizado=_decimal(c[9]) if len(c) > 9 else None, watch=watch or self._watch,
        )

    def _ipos(self, cruda: str, texto: str) -> MensajeDAS:
        return self._pos(cruda, texto, watch=True)

    # ── datos de mercado y de cuenta ──────────────────────────────────
    def _quote(self, cruda: str, texto: str) -> MensajeDAS:
        """$Quote (L1248-1316; §5.19): PARCHE con solo las claves presentes, valores sin convertir, desconocidas conservadas."""
        c = texto.split()
        if len(c) < 2:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        campos: dict[str, str] = {}
        for trozo in c[2:]:
            clave, separador, valor = trozo.partition(":")
            if separador and clave:
                campos[clave] = valor
        return MsgQuote(cruda=cruda, ticker=c[1], campos=campos)

    def _bp(self, cruda: str, texto: str) -> MensajeDAS:
        """BP CurrentBP CurrentOverNightBP (L993-1000)."""
        c = texto.split()
        if len(c) < 3:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgBP(cruda=cruda, bp=_decimal(c[1]), bp_overnight=_decimal(c[2]))

    def _shortinfo(self, cruda: str, texto: str) -> MensajeDAS:
        """$SHORTINFO (L1017-1062): 7 datos + RegSho opcional (añadido 2024-07-02)."""
        c = texto.split()
        if len(c) < 8:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgShortInfo(
            cruda=cruda, ticker=c[1], shortable=_si_no(c[2]), short_size=_entero(c[3]), marginable=_si_no(c[4]),
            tasa_larga=_decimal(c[5]), tasa_corta=_decimal(c[6]), prohibido=_si_no(c[7]),
            reg_sho=_si_no(c[8]) if len(c) > 8 else None,
        )

    def _stinfoex(self, cruda: str, texto: str) -> MensajeDAS:
        """$STINFOEX (L1063-1078; §5.21): texto libre → {"ConcLong": 200, "ConcShr": 50} por regex tolerante."""
        c = texto.split(" ", 2)
        if len(c) < 2:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        libre = c[2] if len(c) > 2 else ""
        valores: dict[str, Decimal] = {}
        for nombre, numero in _RE_STINFOEX.findall(libre):
            valor = _decimal_o_none(numero)
            if valor is not None:
                valores[nombre] = valor
        return MsgStInfoEx(cruda=cruda, ticker=c[1], valores=valores, texto=libre)

    def _ldlu(self, cruda: str, texto: str) -> MensajeDAS:
        """$LDLU symbol limitDown limitUp (L1079-1090)."""
        c = texto.split()
        if len(c) < 4:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgLDLU(cruda=cruda, ticker=c[1], limit_down=_decimal(c[2]), limit_up=_decimal(c[3]))

    def _issuestatus(self, cruda: str, texto: str) -> MensajeDAS:
        """$IssueStatus / $SymStatus (L1101-1133; §5.9): claves `K:V` en cualquier orden; TA/TAT ausentes = normal."""
        c = texto.split()
        if len(c) < 2:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        ssr: Optional[bool] = None
        ta: Optional[str] = None
        tat: Optional[str] = None
        for trozo in c[2:]:
            clave, separador, valor = trozo.partition(":")
            if not separador:
                continue
            clave = clave.upper()
            if clave == "SSR":
                ssr = _si_no_o_none(valor)
            elif clave == "TA":
                ta = valor or None
            elif clave == "TAT":
                tat = valor or None
        return MsgIssueStatus(cruda=cruda, ticker=c[1], ssr=ssr, ta=ta, tat=tat)

    def _accountinfo(self, cruda: str, texto: str) -> MensajeDAS:
        """$AccountInfo (L1143-1158): 10 números."""
        c = texto.split()
        if len(c) < 11:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        numeros = [_decimal(x) for x in c[1:11]]
        return MsgAccountInfo(cruda=cruda, open_eq=numeros[0], curr_eq=numeros[1], realizado=numeros[2],
                              no_realizado=numeros[3], net=numeros[4], htb=numeros[5], sec=numeros[6],
                              finra=numeros[7], ecn=numeros[8], comision=numeros[9])

    # ── locates ───────────────────────────────────────────────────────
    def _slret(self, cruda: str, texto: str) -> MensajeDAS:
        """%SLRET RetType Symbol OfferPrice OfferSize Route Notes [Account] (L1701-1751; §5.4)."""
        p = texto.split(" ", 6)
        if len(p) < 6:
            return MsgDesconocido(cruda=cruda, palabra=p[0])
        notas, cuenta = self._notas_y_cuenta(p[6] if len(p) > 6 else "")
        return MsgSLRet(cruda=cruda, tipo=_entero(p[1]), ticker=p[2], precio=_decimal(p[3]), tamano=_entero(p[4]),
                        ruta=p[5], notas=notas, cuenta=cuenta)

    def _notas_y_cuenta(self, resto: str) -> tuple[str, Optional[str]]:
        """«Notes [Account]» de %SLRET. Con `cuenta` conocida la separación es EXACTA; sin ella, heurística.

        Heurística (documentada, §5.4): notas vacías dejan dos espacios
        (L1710) → el resto empieza por espacio y lo que sigue es la cuenta;
        con dos o más palabras la última es la cuenta; con una sola es una
        nota («AlreadyShortable» de un servidor sin `Account`).
        """
        if not resto.strip():
            return "", None
        if self._cuenta is not None:
            cabeza, _separador, ultimo = resto.rpartition(" ")
            if ultimo == self._cuenta:
                return cabeza.strip(), ultimo
            return resto.strip(), None
        if resto.startswith(" "):
            return "", resto.strip()
        palabras = resto.split()
        if len(palabras) >= 2:
            return " ".join(palabras[:-1]), palabras[-1]
        return palabras[0], None

    def _slorder(self, cruda: str, texto: str) -> MensajeDAS:
        """%SLOrder locateOrderID symbol shares openshares exeshares exeprice status route time lmtPrice [token] notes (L1766-1795)."""
        p = texto.split(" ", 11)
        if len(p) < 10:
            return MsgDesconocido(cruda=cruda, palabra=p[0])
        limite = _decimal_o_none(p[10]) if len(p) > 10 else None
        token: Optional[int] = None
        notas = (p[11] if len(p) > 11 else "").strip()
        if notas:
            primera, _separador, demas = notas.partition(" ")
            candidato = _entero_o_none(primera)
            if candidato is not None and self._nuestro(candidato):
                token, notas = candidato, demas.strip()
        return MsgSLOrder(cruda=cruda, id=_entero(p[1]), ticker=p[2], pedidas=_entero(p[3]), abiertas=_entero(p[4]),
                          localizadas=_entero(p[5]), precio=_decimal(p[6]), estado=p[7], ruta=p[8], hora=p[9],
                          limite=limite, token=token, notas=notas)

    def _slreuse(self, cruda: str, texto: str) -> MensajeDAS:
        """$SLReuseQueryRet Symbol Yes/No (L1818-1822): EP-9."""
        c = texto.split()
        if len(c) < 3:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        valor = c[2].lower()
        if valor in ("yes", "y"):
            reutilizable = True
        elif valor in ("no", "n"):
            reutilizable = False
        else:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgSLReuse(cruda=cruda, ticker=c[1], reutilizable=reutilizable)

    def _slavail(self, cruda: str, texto: str) -> MensajeDAS:
        """$SLAvailQueryRet Account Symbol AvailableLocateShares (L1804-1809)."""
        c = texto.split()
        if len(c) < 4:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgSLAvail(cruda=cruda, cuenta=c[1], ticker=c[2], disponibles=_entero(c[3]))

    def _slmincharge(self, cruda: str, texto: str) -> MensajeDAS:
        """SLRouteMinChargeRet Route $minCharge, con o sin `$` delante de la palabra (L1833-1838; §5.10)."""
        c = texto.split()
        if len(c) < 3:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgSLMinCharge(cruda=cruda, ruta=c[1], minimo=_decimal(c[2].lstrip("$")))

    # ── varios ────────────────────────────────────────────────────────
    def _routestatus(self, cruda: str, texto: str) -> MensajeDAS:
        """$RouteStatus ROUTE Enabled/Disabled (L1566-1574): sin marcador de fin."""
        c = texto.split()
        if len(c) < 3:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        estado = c[2].lower()
        if estado not in ("enabled", "disabled"):
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgRouteStatus(cruda=cruda, ruta=c[1], habilitada=(estado == "enabled"))

    def _intmsg(self, cruda: str, texto: str) -> MensajeDAS:
        """$INTMSG multilínea (L1575-1610): se acumula hasta `Msg:`; `\\t` = salto de línea en `Msg`.

        Las partes intermedias (`Send Time`, `From`, `To`, `Title`) se
        devuelven como `MsgInformativo("$INTMSG")`; la parte `Msg` cierra el
        mensaje y devuelve `MsgIntMsg` con todos los campos. Un `Send Time`
        nuevo reinicia la acumulación (no hay marcador de fin explícito).
        """
        partes = texto.split(" ", 1)
        resto = partes[1] if len(partes) > 1 else ""
        clave, separador, valor = resto.partition(":")
        clave = clave.strip()
        if not separador or not clave:
            return MsgDesconocido(cruda=cruda, palabra=partes[0])
        valor = valor.strip()
        if clave.lower() == "send time":
            self._intmsg = {}
        self._intmsg[clave] = valor
        if clave.lower() != "msg":
            return MsgInformativo(cruda=cruda, palabra="$INTMSG")
        campos = dict(self._intmsg)
        campos[clave] = valor.replace("\t", "\n")
        self._intmsg = {}
        return MsgIntMsg(cruda=cruda, campos=campos)

    def _ts(self, cruda: str, texto: str) -> MensajeDAS:
        """$T&S symbol price volume flag time Exchange B/S/I condition (L1317-1360; §5.20: condición entero decimal)."""
        c = texto.split()
        if len(c) < 9:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgTS(cruda=cruda, ticker=c[1], precio=_decimal(c[2]), volumen=_entero(c[3]), flag=c[4], hora=c[5],
                     bolsa=c[6], lado=c[7], condicion=_entero(c[8]))

    def _bar(self, cruda: str, texto: str) -> MensajeDAS:
        """$Bar symbol date[-time] High Low Open Close Volume [MinType] (L1373-1435): HLOC, no OHLC."""
        c = texto.split()
        if len(c) < 8:
            return MsgDesconocido(cruda=cruda, palabra=c[0])
        return MsgBar(cruda=cruda, ticker=c[1], cuando=c[2], high=_decimal(c[3]), low=_decimal(c[4]),
                      open=_decimal(c[5]), close=_decimal(c[6]), volumen=_entero(c[7]),
                      min_type=_entero(c[8]) if len(c) > 8 else None)


_MANEJADORES: dict[str, Callable[[Parser, str, str], MensajeDAS]] = {
    "%ORDER": Parser._orden, "%IORDER": Parser._iorden, "%ORDERACT": Parser._orderact,
    "%TRADE": Parser._trade, "%ITRADE": Parser._itrade, "%POS": Parser._pos, "%IPOS": Parser._ipos,
    "$QUOTE": Parser._quote, "BP": Parser._bp, "$SHORTINFO": Parser._shortinfo, "$STINFOEX": Parser._stinfoex,
    "$LDLU": Parser._ldlu, "$ISSUESTATUS": Parser._issuestatus, "$SYMSTATUS": Parser._issuestatus,
    "$ACCOUNTINFO": Parser._accountinfo, "%SLRET": Parser._slret, "%SLORDER": Parser._slorder,
    "$SLREUSEQUERYRET": Parser._slreuse, "$SLAVAILQUERYRET": Parser._slavail,
    "SLROUTEMINCHARGERET": Parser._slmincharge, "$SLROUTEMINCHARGERET": Parser._slmincharge,
    "$ROUTESTATUS": Parser._routestatus, "$INTMSG": Parser._intmsg, "$T&S": Parser._ts, "$BAR": Parser._bar,
}


def parsear(linea: str, es_nuestro: Callable[[int], bool] = lambda t: True) -> MensajeDAS:
    """Atajo sin estado para tests: `Parser(es_nuestro).parsear(linea)`."""
    return Parser(es_nuestro).parsear(linea)


def normalizar_pos(ticker: str, tipo: int, qty_cruda: int, qty_corto_negativa: Optional[bool]) -> int:
    """Neta SIGNADA de una `%POS` (injerto A §8.8): tipo 3 (corto) → −abs(qty); tipo 1/2 → abs(qty).

    `qty_corto_negativa` solo se registra (lo confirma `comprobar_das.py` el
    primer día): la normalización NO depende de él, por eso es segura tanto si
    DAS manda los cortos en negativo como en positivo. Un tipo desconocido
    (ni 1, 2 ni 3) se devuelve tal cual llegó: no se inventa un signo.
    `ticker` solo sirve para el mensaje de error.
    """
    if type(tipo) is not int or type(qty_cruda) is not int:
        raise ValueError(f"{ticker}: tipo y qty deben ser int: {tipo!r}, {qty_cruda!r}")
    if tipo == 3:
        return -abs(qty_cruda)
    if tipo in (1, 2):
        return abs(qty_cruda)
    return qty_cruda


def redactar(linea: str) -> str:
    """Tapa la clave del LOGIN («LOGIN u ***** acc 0») y cualquier token de Telegram (R-Q-01, riesgo 20).

    Es lo ÚNICO que puede llegar a un log o al diario desde el cliente.
    Trampas: el LOGIN puede ir en mitad de un texto («enviado: LOGIN …») o
    repetirse, así que se tapan TODAS las apariciones (tapar de más es
    inofensivo; de menos, una fuga); el token de Telegram se tapa con y sin
    el prefijo `bot` (`bot123:AA…` en una URL, `123:AA…` suelto). NUNCA
    lanza: un objeto que no es texto se convierte con `str`.
    """
    if not isinstance(linea, str):
        linea = str(linea)
    linea = _RE_LOGIN.sub(lambda m: f"{m.group(1)}*****", linea)
    linea = _RE_TOKEN_TELEGRAM.sub("bot***:*****", linea)
    return _RE_TOKEN_TELEGRAM_SUELTO.sub("***:*****", linea)


# ══════════════════════════════════════════════════════════════════════
# ayudantes privados
# ══════════════════════════════════════════════════════════════════════
def _primera_palabra(texto: str) -> str:
    partes = texto.split(None, 1)
    return partes[0] if partes else ""


def _lado(x: str) -> str:
    """B/Buy → B; S/Sell → S; SS/Shrt/Short → SS; lo desconocido se conserva tal cual (§5.5)."""
    return LADOS.get(x.upper(), x)


def _entero(x: str) -> int:
    if not _RE_ENTERO.fullmatch(x):
        raise ValueError(f"entero esperado: {x!r}")
    return int(x)


def _entero_o_none(x: str) -> Optional[int]:
    return int(x) if _RE_ENTERO.fullmatch(x) else None


def _decimal(x: str) -> Decimal:
    try:
        valor = Decimal(x)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"número esperado: {x!r}") from exc
    if not valor.is_finite():
        raise ValueError(f"número no finito: {x!r}")
    return valor


def _decimal_o_none(x: str) -> Optional[Decimal]:
    try:
        return _decimal(x)
    except ValueError:
        return None


def _decimal_o_cero(x: str) -> Decimal:
    """Precio «solo de referencia» (L475-477): no numérico → 0 antes que perder la orden entera."""
    valor = _decimal_o_none(x)
    return valor if valor is not None else Decimal("0")


def _si_no(x: str) -> bool:
    valor = _si_no_o_none(x)
    if valor is None:
        raise ValueError(f"Y/N esperado: {x!r}")
    return valor


def _si_no_o_none(x: str) -> Optional[bool]:
    v = x.strip().upper()
    if v in ("Y", "YES", "1", "TRUE"):
        return True
    if v in ("N", "NO", "0", "FALSE"):
        return False
    return None


def _palabra(nombre: str, valor: str) -> str:
    """Un campo de comando: texto no vacío y sin espacios ni saltos (un espacio desplazaría los campos)."""
    if not isinstance(valor, str) or not valor or valor != valor.strip() or any(ch.isspace() for ch in valor):
        raise ValueError(f"{nombre} inválido para el protocolo: {valor!r}")
    return valor


def _entero_positivo(nombre: str, valor: int) -> int:
    if type(valor) is not int or valor <= 0:
        raise ValueError(f"{nombre} debe ser int > 0: {valor!r}")
    return valor


def _token(nombre: str, valor: int) -> int:
    """int32 con signo (manual L595-597); `bool` y `float` no valen."""
    if type(valor) is not int or not (_MIN_INT32 <= valor <= _MAX_INT32):
        raise ValueError(f"{nombre} fuera de int32: {valor!r}")
    return valor


def _canal(canal: str) -> str:
    if not isinstance(canal, str) or canal.strip().upper() not in _CANALES:
        raise ValueError(f"canal de SB no admitido: {canal!r} (admitidos: {', '.join(CANALES_SB)})")
    return _CANALES[canal.strip().upper()]
