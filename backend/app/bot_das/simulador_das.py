"""«DAS falso»: servidor TCP que habla el CMD API de DAS, con libro y motor de cruce deterministas.

QUÉ HACE. Tres piezas y un guion:
  * `LibroSimulado`: cotizaciones, estado del símbolo (halt, SSR, bandas),
    órdenes, trades, posiciones y locates de UNA cuenta inventada. Es solo
    datos (con un cerrojo): no cruza nada.
  * `Emparejador`: el motor de cruce. Recibe una línea de comando
    (`NEWORDER`, `CANCEL`, `REPLACE`, `SL*`, `GET`, `POSREFRESH`) y devuelve
    las líneas que DAS mandaría (`%OrderAct`, `%ORDER`, `%TRADE`, `%POS`,
    `%SLOrder`, `%SLRET`, `BP`, `$IssueStatus`…); `tic()` dispara stops y
    llena lo que reposa. PURO salvo el reloj (la hora de cada línea). Lo usan
    `SimuladorDAS` y, en la fase sombra, `cliente.ClienteSombra` (R-O-03).
  * `SimuladorDAS`: servidor TCP en un hilo, en `127.0.0.1:0`, con N
    conexiones normales y watch (último campo del LOGIN). Como el DAS real
    (01-oct): al conectar saluda («#Welcome to DAS Command API», «#Please
    login to continue.»); un LOGIN bueno recibe «#LOGIN SUCCESSED» (sic), los
    estados `#OrderServer/#QuoteServer:Logon:Successful` (del manual; el DAS
    real no los mandó, se conservan por compatibilidad) y el volcado
    `#POS…#POSEND`, `#Order…#OrderEnd`, `#Trade…#TradeEnd`; uno malo,
    «ERROR:INVALID PASSWORD» y nada más (lo demás se ignora); la
    conexión watch recibe `%IORDER/%IPOS/%ITRADE` de todo; `SB/UNSB` reparten
    `$Quote`; `cortar` simula el EOF de R-J-02; `emitir`/`emitir_crudo`
    permiten inyectar líneas (enteras o a trozos) y `recibidas()` devuelve lo
    que llegó (para asertar «ningún mutante» en sombra).
  * `ProgramaGuion` + `main`: el guion del replay (spread declarado, halts,
    rechazos y fills parciales, injerto A §8.24) y
    `python -m app.bot_das.simulador_das --puerto N --guion f.json`.

Reglas de cruce (§3.3): una venta límite se llena al LLEGAR si `precio ≤ bid`
(al bid; con PostOnly → `Send_Rej "PostOnly would cross"`); si no, reposa y se
llena a SU precio cuando `bid ≥ precio`. La compra es simétrica con el ask.
`MKT` se llena al ask/bid. Un `STOPLMTP` de compra se dispara cuando
`last ≥ stop` (venta: `last ≤ stop`) y pasa a límite. Parciales por
`llenar_parcial` (tope de llenado por orden) o por el tamaño del libro (se
consume). La ruta `OPEN` durante un halt se acepta y se llena al precio de
`reabrir` (EP-2), o se rechaza si `open_en_halt="rechazar"`.

POR QUÉ ESTÁ AQUÍ. Los tests del cliente, del ejecutor y del vigilante
necesitan un DAS que hable EXACTAMENTE el protocolo (§4) sin tocar el DAS
real (§10). El `Emparejador` es a la vez el motor de la sombra: los mutantes
nunca salen al socket real y producen fills SIMULADOS con las mismas reglas.
Las variantes NO documentadas del manual son parámetros para que el bot se
pruebe con todas: `variante_order` (15/19 campos, §5.3), `tipo_stop_crudo`
(«SLP: 2.97 2.99», §5.2), `replace_conserva_pp` (§5.6), `orden_mensajes`
(las 6 permutaciones de `%OrderAct`/`%TRADE`/`%POS`, §5.12, riesgo 8) y
`qty_corto_negativa` (signo de `%POS` en cortos, §5.12, riesgo 9).

LAS TRAMPAS.
  * Todo precio es `Decimal` (riesgo 12): las velas del replay traen `float`
    y se convierten UNA vez con `de_float` (`Decimal(str(x))`); las
    acciones son `int` puros. Las líneas salen sin notación científica
    (`_num`).
  * `%OrderAct` con notas vacías lleva DOS espacios antes del token
    (manual L934-936): el parser del bot debe sobrevivir a eso, así que el
    simulador lo produce igual.
  * `%ITRADE` NO es `%TRADE` renombrado: la cuenta va primero y el trader al
    final (L1446-1458). `_a_watch` lo reordena.
  * `$Quote` lleva los tamaños en LOTES (manual L1283-1289: «Number of
    lots»); el libro los guarda en ACCIONES. `tamano_*` None = liquidez sin
    tope.
  * `REPLACE id share …`: el manual no precisa si `share` es la NUEVA
    cantidad ABIERTA (lvqty) o la TOTAL (llenas + abierta). A-02: el
    `Emparejador` sigue el mismo interruptor que el decisor
    (`replace_share_es_abierta`, defecto `tipos.REPLACE_SHARE_ES_ABIERTA`;
    en `main`, `--replace-share-total`), así el bot se prueba con las dos
    lecturas y el canario de `comprobar_das` decide cuál es la real.
  * Nada se ejecuta al importar: ni sockets ni hilos. Los hilos son daemon y
    `parar()` los une con plazo; la emisión va bajo un cerrojo para que el
    orden de las líneas sea el mismo en todas las conexiones.
  * Los usuarios del simulador los inventa el test (`{"prueba": "prueba"}`);
    las credenciales de ejemplo del manual (L246-247) no aparecen jamás.
    Sin `usuarios` se acepta cualquier LOGIN.
  * El python del venv en Windows es un lanzador: si un test lanza `main` en
    un subproceso, `Popen.pid` no es el PID del intérprete (trampa del lote 0).
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from datetime import time as dtime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from app.bot_das.protocolo import CODIFICACION, FIN_LINEA
from app.bot_das.reglas.precios import de_float
from app.bot_das.reloj import Reloj
from app.bot_das.tipos import REPLACE_SHARE_ES_ABIERTA, EstadoOrden, TipoOrden, al_tick, en_tick, tick_de

# ── constantes públicas del simulador ─────────────────────────────────
CUENTA_SIMULADA = "CUENTA_PRUEBA"          # inventada; la misma que usan las fixtures de los tests
TRADER_SIMULADO = "TRPRUEBA"
BP_SIMULADO = Decimal("100000")
RUTAS_SIMULADAS = ("SAGEREB", "SAGEPRO", "SAGEREBL", "MIAX", "EDGA", "SMAT", "STOP", "OPEN")   # rutas de config_ejemplo + SMAT/SAGEREBL
RUTA_LOCATE_SIMULADA = "LOCSIM"
PRECIO_LOCATE_SIMULADO = Decimal("0.01")
LOCATES_DISPONIBLES_SIMULADOS = 1_000_000
ORDEN_MENSAJES_DEFECTO = ("OrderAct", "TRADE", "POS")
OPEN_EN_HALT = ("aceptar", "rechazar")
CORTES = ("todas", "normal", "watch")
ACCIONES_RECHAZO = ("Send_Rej", "CancelRej", "ReplaceRej")
PRIMER_ID_ORDEN = 1001
PRIMER_ID_TRADE = 5001
PRIMER_ID_LOCATE = 9001
# Textos de rechazo INVENTADOS por el simulador (los reales de Sage se catalogan en canario, §10).
NOTA_POSTONLY = "PostOnly would cross"     # §3.3 literal
NOTA_PRECIO = "Invalid price"
NOTA_CANTIDAD = "Invalid quantity"
NOTA_STOP = "Invalid stop price"
NOTA_POSTONLY_TIPO = "PostOnly only for limit orders"
NOTA_OPEN_HALT = "OPEN route not available during halt"
NOTA_TIPO_NO_SIMULADO = "Order type not simulated"
NOTA_NO_ABIERTA = "Order not open"
NOTA_TIPO_REPLACE = "Replace type mismatch"
NOTA_LOCATE_TIPO1 = "Route type 1 does not support inquire"
# Saludo y respuestas al LOGIN COPIADOS del DAS real (01-oct; el manual no los documenta).
BIENVENIDA = ("#Welcome to DAS Command API", "#Please login to continue.")
LOGIN_ACEPTADO = "#LOGIN SUCCESSED"
LOGIN_RECHAZADO = "ERROR:INVALID PASSWORD"

# Encabezados de los volcados (manual L272-276, L343-346, L506, L1752-1755).
CABECERA_POS = "#POS symb type qty avgcost initqty initprice Realized CreateTime Unrealized"
CABECERA_ORDER_19 = ("#Order id token symb b/s mkt/lmt qty lvqty cxlqty price route status time "
                     "origoid account trader orderSrc TIF Pref")
CABECERA_ORDER_15 = "#Order id token symb b/s mkt/lmt qty lvqty cxlqty price route status time origoid account trader"
CABECERA_TRADE = "#Trade id symb B/S qty price route time orderid Liq EcnFee PL"
CABECERA_SLORDER = "#SLOrder id symb shares openshares exeshares exeprice status route time lmtPrice token notes"

_VIVAS = frozenset({EstadoOrden.ACCEPTED.value, EstadoOrden.PARTIAL.value})
_LADOS_ORDEN = ("B", "S", "SS")
_LADO_ORDERACT = {"B": "Buy", "S": "Sell", "SS": "Shrt"}     # §5.5: %OrderAct trae Buy/Shrt
_TA_PARADO = frozenset({"H", "P", "Q"})                      # manual L1113-1120: halt, pausa, solo cotización
_TIPOS_NO_SIMULADOS = frozenset({"STOPMKT", "STOPLMT", "PEG", "STOPTRAILING", "RANGE", "RANGEMKT"})
_EVENTOS = frozenset({"%ORDER", "%ORDERACT", "%TRADE", "%POS", "%SLORDER"})   # se difunden a todas las conexiones
_RE_ENTERO = re.compile(r"[+-]?\d+")
_RE_HORA = re.compile(r"(\d{2}):(\d{2})(?::(\d{2}))?")
_MAX_INT32 = 2**31 - 1
_MIN_INT32 = -(2**31)
_TIMEOUT_SOCKET_S = 0.2
_ESPERA_UNION_S = 2.0


class _ComandoMalo(ValueError):
    """Línea que no casa con la gramática del comando: DAS no acusa la sintaxis (§5.15); aquí queda en `incidencias`."""


# ══════════════════════════════════════════════════════════════════════
# Modelo de spread (injerto A §8.24)
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ModeloSpread:
    """Spread declarado para el replay: las grabaciones `AM_*.jsonl.gz` no traen bid/ask (grabador.py l.26-40).

    `pct` = spread TOTAL en % del cierre (Decimal), con un mínimo de
    `minimo_ticks` ticks; `tamano_bid`/`tamano_ask` en ACCIONES. Riesgo 28:
    los fills del replay no son comparables con los reales; el test dorado
    compara señales, decisiones y tokens, no precios.
    """
    pct: Decimal = Decimal("0.5")
    minimo_ticks: int = 1
    tamano_bid: int = 500
    tamano_ask: int = 500

    def __post_init__(self) -> None:
        if not isinstance(self.pct, Decimal) or not self.pct.is_finite() or self.pct < 0:
            raise ValueError(f"ModeloSpread.pct debe ser un Decimal finito ≥ 0: {self.pct!r}")
        for nombre, minimo in (("minimo_ticks", 0), ("tamano_bid", 1), ("tamano_ask", 1)):
            valor = getattr(self, nombre)
            if type(valor) is not int or valor < minimo:
                raise ValueError(f"ModeloSpread.{nombre} debe ser un int ≥ {minimo}: {valor!r}")

    def precios(self, cierre: Decimal) -> tuple[Decimal, Decimal]:
        """(bid, ask) alrededor de `cierre` (injerto A §8.24).

        Spread total = max(cierre·pct/100 redondeado ARRIBA al tick del cierre,
        minimo_ticks·tick); bid = cierre − spread/2 redondeado ABAJO; ask =
        bid + spread. Trampas: el tick es el del CIERRE (un 0,01225 suelto
        tendría tick de 0,0001, regla 612); un bid ≤ 0 se sube a un tick; un ask
        que cruza 1 $ desde abajo se sube al tick de céntimos (sigue al tick).
        """
        if not isinstance(cierre, Decimal) or not cierre.is_finite() or cierre <= 0:
            raise ValueError(f"cierre inválido para el spread: {cierre!r}")
        tick = tick_de(cierre)
        bruto = cierre * self.pct / 100
        total = (bruto / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        total = max(total, tick * self.minimo_ticks)
        bid = ((cierre - total / 2) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        if bid <= 0:
            bid = tick
        ask = bid + total
        if not en_tick(ask):
            ask = al_tick(ask, arriba=True)
        return bid, ask


# ══════════════════════════════════════════════════════════════════════
# Libro: solo datos
# ══════════════════════════════════════════════════════════════════════
@dataclass
class _OrdenSim:
    """Orden viva o histórica del simulador (privada: fuera se ve como dict por `LibroSimulado.ordenes`)."""
    id: int
    token: int
    ticker: str
    lado: str                    # B | S | SS
    tipo: str                    # valores de TipoOrden: LMT | MKT | STOPLMTP
    qty: int
    ruta: str
    tif: str
    pref: Optional[str]
    post_only: bool
    precio: Optional[Decimal]
    stop: Optional[Decimal]
    estado: str = EstadoOrden.SENDING.value
    lvqty: int = 0
    cxlqty: int = 0
    llenas: int = 0
    disparada: bool = False
    pp_perdido: bool = False     # REPLACE con replace_conserva_pp=False: DAS la convirtió en STOPLMT (§5.6)
    tope_llenado: Optional[int] = None
    hora: str = "00:00:00"


class LibroSimulado:
    """Cotizaciones, estado de símbolos, órdenes, trades, posiciones y locates de UNA cuenta simulada. Determinista.

    Solo datos: no cruza (eso es del `Emparejador`). Todas las operaciones
    toman `cerrojo` (RLock): el hilo del servidor y el del test lo comparten.
    `rutas`, `bp`, `bp_overnight` y `equity_inicial` son atributos públicos
    que el test puede cambiar para las respuestas de `GET`.
    """

    def __init__(self, cuenta: str = CUENTA_SIMULADA, trader: str = TRADER_SIMULADO,
                 bp: Decimal = BP_SIMULADO) -> None:
        self.cuenta = _palabra("cuenta", cuenta)
        self.trader = _palabra("trader", trader)
        self.bp = _precio_positivo("bp", bp)
        self.bp_overnight = self.bp
        self.equity_inicial = self.bp
        self.rutas: dict[str, bool] = {r: True for r in RUTAS_SIMULADAS}
        self.cerrojo = threading.RLock()
        self._quotes: dict[str, dict[str, Any]] = {}
        self._simbolos: dict[str, dict[str, Any]] = {}
        self._reaperturas: dict[str, Decimal] = {}
        self._rechazos: list[dict[str, Any]] = []
        self._parcial_global: Optional[Decimal] = None
        self._parcial_ticker: dict[str, Decimal] = {}
        self._ordenes: dict[int, _OrdenSim] = {}
        self._trades: list[dict[str, Any]] = []
        self._pos: dict[str, dict[str, Any]] = {}
        self._locates: dict[int, dict[str, Any]] = {}
        self._cfg_locates: dict[str, dict[str, Any]] = {}
        self._min_charge: dict[str, Decimal] = {RUTA_LOCATE_SIMULADA: Decimal("0")}
        self._sig_orden = PRIMER_ID_ORDEN
        self._sig_trade = PRIMER_ID_TRADE
        self._sig_locate = PRIMER_ID_LOCATE

    # ── mercado ───────────────────────────────────────────────────────
    def cotizar(self, ticker: str, bid: Decimal, ask: Decimal, last: Optional[Decimal] = None, volumen: int = 0,
                vwap: Optional[Decimal] = None, tamano_bid: Optional[int] = None,
                tamano_ask: Optional[int] = None) -> list[str]:
        """Fija la cotización Lv1 de `ticker` y devuelve la línea `$Quote` a emitir (manual L1248-1316).

        Precios por `de_float` (riesgo 12: nunca float en aritmética); `bid`
        y `ask` > 0 con `ask ≥ bid`. `tamano_*` en ACCIONES (None = sin tope:
        liquidez infinita); en la línea van en LOTES de 100. Cada llamada
        SUSTITUYE la cotización entera (tamaños incluidos) salvo `last`, que
        se conserva si no se da (un print no llega con cada cambio de bid/ask).
        """
        ticker = _palabra("ticker", ticker)
        b = _precio_positivo("bid", bid)
        a = _precio_positivo("ask", ask)
        if a < b:
            raise ValueError(f"{ticker}: libro cruzado (ask {a} < bid {b})")
        ultimo = _precio_positivo("last", last) if last is not None else None
        media = _precio_positivo("vwap", vwap) if vwap is not None else None
        if type(volumen) is not int or volumen < 0:
            raise ValueError(f"volumen debe ser int ≥ 0: {volumen!r}")
        for nombre, valor in (("tamano_bid", tamano_bid), ("tamano_ask", tamano_ask)):
            if valor is not None and (type(valor) is not int or valor < 0):
                raise ValueError(f"{nombre} debe ser int ≥ 0 o None: {valor!r}")
        with self.cerrojo:
            anterior = self._quotes.get(ticker, {})
            self._quotes[ticker] = {
                "bid": b, "ask": a, "last": ultimo if ultimo is not None else anterior.get("last"),
                "volumen": volumen, "vwap": media, "tamano_bid": tamano_bid, "tamano_ask": tamano_ask,
            }
            return [self.linea_quote(ticker)]

    def desde_vela(self, ticker: str, vela: dict, spread: ModeloSpread) -> list[str]:
        """Replay (injerto A §8.24): `close` → last; bid/ask = `spread.precios(close)`; tamaños del modelo.

        `vela` es el dict de `fuente_senales` (`open/high/low/close/volume`
        como float): se convierten UNA vez con `de_float`. `volume` ausente → 0;
        `vwap` opcional.
        """
        if not isinstance(vela, dict) or "close" not in vela:
            raise ValueError(f"vela sin 'close': {vela!r}")
        if not isinstance(spread, ModeloSpread):
            raise ValueError(f"spread debe ser un ModeloSpread: {spread!r}")
        cierre = _precio_positivo("close", vela["close"])
        bid, ask = spread.precios(cierre)
        volumen_crudo = vela.get("volume")
        volumen = int(de_float(volumen_crudo)) if volumen_crudo is not None else 0
        vwap = vela.get("vwap")
        return self.cotizar(ticker, bid, ask, last=cierre, volumen=max(volumen, 0),
                            vwap=de_float(vwap) if vwap is not None else None,
                            tamano_bid=spread.tamano_bid, tamano_ask=spread.tamano_ask)

    def linea_quote(self, ticker: str) -> str:
        """`$Quote` COMPLETA con lo que el libro sabe del ticker (la que se manda al suscribir)."""
        with self.cerrojo:
            q = self._quotes.get(ticker)
            if q is None:
                return f"$Quote {ticker}"
            partes = [f"$Quote {ticker}", f"A:{_num(q['ask'])}"]
            if q["tamano_ask"] is not None:
                partes.append(f"Asz:{q['tamano_ask'] // 100}")
            partes.append(f"B:{_num(q['bid'])}")
            if q["tamano_bid"] is not None:
                partes.append(f"Bsz:{q['tamano_bid'] // 100}")
            if q["volumen"]:
                partes.append(f"V:{q['volumen']}")
            if q["last"] is not None:
                partes.append(f"L:{_num(q['last'])}")
            if q["vwap"] is not None:
                partes.append(f"VWAP:{_num(q['vwap'])}")
            return " ".join(partes)

    def cotizacion(self, ticker: str) -> Optional[dict[str, Any]]:
        """Copia de la cotización actual (bid, ask, last, volumen, vwap, tamano_bid, tamano_ask) o None."""
        with self.cerrojo:
            q = self._quotes.get(ticker)
            return dict(q) if q is not None else None

    def halt(self, ticker: str, ta: str, tat: str) -> None:
        """Para el símbolo (R-F-01): `ta` ∈ H/P/Q (manual L1113-1120), `tat` = HH:MM:SS. Nada se llena mientras."""
        ticker = _palabra("ticker", ticker)
        if ta not in _TA_PARADO:
            raise ValueError(f"TA de halt debe ser H, P o Q: {ta!r}")
        with self.cerrojo:
            simb = self._simbolo(ticker)
            simb["ta"] = ta
            simb["tat"] = _palabra("tat", tat)
            self._reaperturas.pop(ticker, None)

    def reabrir(self, ticker: str, precio: Decimal, tat: Optional[str] = None) -> None:
        """Reapertura (R-F-01, EP-2): TA:T y las órdenes por ruta OPEN se llenan a `precio` en el próximo `tic()`.

        El libro de antes del halt ya no vale: bid = ask = last = `precio`
        (sin tope de tamaño) hasta la siguiente `cotizar`. Así una límite
        que reposaba no se llena contra una cotización vieja.
        """
        ticker = _palabra("ticker", ticker)
        p = _precio_positivo("precio", precio)
        with self.cerrojo:
            simb = self._simbolo(ticker)
            simb["ta"] = "T"
            simb["tat"] = _palabra("tat", tat) if tat is not None else simb.get("tat")
            anterior = self._quotes.get(ticker, {})
            self._quotes[ticker] = {"bid": p, "ask": p, "last": p, "volumen": anterior.get("volumen", 0),
                                    "vwap": anterior.get("vwap"), "tamano_bid": None, "tamano_ask": None}
            self._reaperturas[ticker] = p

    def en_halt(self, ticker: str) -> bool:
        """True si el TA vigente es H, P o Q."""
        with self.cerrojo:
            return self._simbolos.get(ticker, {}).get("ta") in _TA_PARADO

    def bandas(self, ticker: str, ld: Decimal, lu: Decimal) -> None:
        """Limit down / limit up para `GET LDLU` (R-F-02). Sin bandas, `GET LDLU` no responde nada (manual L1086-1088)."""
        ticker = _palabra("ticker", ticker)
        abajo = _precio_positivo("ld", ld)
        arriba = _precio_positivo("lu", lu)
        if arriba < abajo:
            raise ValueError(f"{ticker}: limit up {arriba} < limit down {abajo}")
        with self.cerrojo:
            simb = self._simbolo(ticker)
            simb["ld"], simb["lu"] = abajo, arriba

    def ssr(self, ticker: str, activo: bool) -> None:
        """SSR del símbolo para `GET SymStatus` (R-B-05). No cambia las reglas de cruce."""
        ticker = _palabra("ticker", ticker)
        with self.cerrojo:
            self._simbolo(ticker)["ssr"] = bool(activo)

    # ── guion de fallos ───────────────────────────────────────────────
    def rechazar_siguiente(self, notas: str, accion: str = "Send_Rej", token_o_orden: Optional[int] = None) -> None:
        """El próximo comando del tipo de `accion` se rechaza con `notas` (R-B-07, EP-1).

        `Send_Rej` → el próximo NEWORDER; `CancelRej` → el próximo CANCEL;
        `ReplaceRej` → el próximo REPLACE. Con `token_o_orden` solo el de ese
        token o ese id de DAS. Los rechazos se consumen en orden de llegada.
        """
        if not isinstance(notas, str) or "\n" in notas or "\r" in notas:
            raise ValueError(f"notas de rechazo inválidas: {notas!r}")
        if accion not in ACCIONES_RECHAZO:
            raise ValueError(f"acción de rechazo desconocida: {accion!r} (admitidas: {', '.join(ACCIONES_RECHAZO)})")
        if token_o_orden is not None and type(token_o_orden) is not int:
            raise ValueError(f"token_o_orden debe ser int o None: {token_o_orden!r}")
        with self.cerrojo:
            self._rechazos.append({"notas": notas.strip(), "accion": accion, "token_o_orden": token_o_orden})

    def llenar_parcial(self, fraccion: Decimal, ticker: Optional[str] = None) -> None:
        """Las PRÓXIMAS órdenes (de `ticker`, o de todos) se llenan como mucho `floor(qty·fraccion)` (mínimo 1).

        El resto queda vivo (`Partial`) y no se llena más: así se prueba la
        cancelación del resto (R-B-02). `fraccion` ∈ (0, 1]; 1 deja de limitar.
        Lo del ticker manda sobre lo global.
        """
        f = de_float(fraccion)
        if not (0 < f <= 1):
            raise ValueError(f"fracción de llenado fuera de (0, 1]: {fraccion!r}")
        with self.cerrojo:
            if ticker is None:
                self._parcial_global = None if f == 1 else f
            else:
                ticker = _palabra("ticker", ticker)
                if f == 1:
                    self._parcial_ticker.pop(ticker, None)
                else:
                    self._parcial_ticker[ticker] = f

    def sembrar_posicion(self, ticker: str, neta: int, precio_medio: Decimal,
                         creada: str = "1970/01/01-00:00:00") -> None:
        """Posición previa al LOGIN (arranque con posiciones, F12/F13): sale en el volcado y en `GET POSITIONS`."""
        ticker = _palabra("ticker", ticker)
        if type(neta) is not int:
            raise ValueError(f"neta debe ser int: {neta!r}")
        medio = _precio_positivo("precio_medio", precio_medio)
        with self.cerrojo:
            self._pos[ticker] = {"neta": neta, "avg": medio, "realizado": Decimal("0"),
                                 "tipo": 3 if neta < 0 else 2, "creada": _palabra("creada", creada)}

    def configurar_locate(self, ticker: str, precio: Optional[Decimal] = None, disponibles: Optional[int] = None,
                          ruta: Optional[str] = None, tipo_ruta: Optional[int] = None,
                          reutilizable: Optional[bool] = None, fallo: Optional[str] = None,
                          minimo: Optional[Decimal] = None) -> None:
        """Oferta de locates de `ticker` (R-H-01..05). Por defecto: 0,01 $/acción, 1.000.000 disponibles, ruta LOCSIM tipo 0, reutilizable.

        `tipo_ruta=1` → las compras quedan `Offered` hasta `SLOFFEROPERATION`;
        `fallo` (p. ej. "AlreadyShortable", una palabra) → `%SLRET 2` con ese
        motivo, y `fallo=""` lo quita; `minimo` = cargo mínimo de la ruta
        (`SLRouteMinCharge`).
        """
        ticker = _palabra("ticker", ticker)
        with self.cerrojo:
            cfg = self._cfg_locate(ticker)
            if precio is not None:
                cfg["precio"] = _precio_no_negativo("precio", precio)
            if disponibles is not None:
                if type(disponibles) is not int or disponibles < 0:
                    raise ValueError(f"disponibles debe ser int ≥ 0: {disponibles!r}")
                cfg["disponibles"] = disponibles
            if ruta is not None:
                cfg["ruta"] = _palabra("ruta", ruta)
            if tipo_ruta is not None:
                if tipo_ruta not in (0, 1) or type(tipo_ruta) is not int:
                    raise ValueError(f"tipo_ruta debe ser 0 o 1: {tipo_ruta!r}")
                cfg["tipo_ruta"] = tipo_ruta
            if reutilizable is not None:
                cfg["reutilizable"] = bool(reutilizable)
            if fallo is not None:
                cfg["fallo"] = _palabra("fallo", fallo) if fallo else None
            if minimo is not None:
                self._min_charge[cfg["ruta"]] = _precio_no_negativo("minimo", minimo)
            else:
                self._min_charge.setdefault(cfg["ruta"], Decimal("0"))

    # ── consultas para los tests ──────────────────────────────────────
    def ordenes(self) -> list[dict[str, Any]]:
        """Todas las órdenes (vivas y cerradas) en orden de llegada, como dicts."""
        with self.cerrojo:
            return [{
                "id": o.id, "token": o.token, "ticker": o.ticker, "lado": o.lado, "tipo": o.tipo, "qty": o.qty,
                "lvqty": o.lvqty, "cxlqty": o.cxlqty, "llenas": o.llenas, "precio": o.precio, "stop": o.stop,
                "ruta": o.ruta, "estado": o.estado, "tif": o.tif, "pref": o.pref, "post_only": o.post_only,
                "disparada": o.disparada, "hora": o.hora,
            } for o in self._ordenes.values()]

    def posiciones(self) -> dict[str, int]:
        """{ticker: neta SIGNADA} (corto < 0), incluidas las que quedaron a 0."""
        with self.cerrojo:
            return {t: p["neta"] for t, p in self._pos.items()}

    def trades(self) -> list[dict[str, Any]]:
        """Ejecuciones en orden: id, ticker, lado, qty, precio, ruta, hora, id_orden, token, liq, pl."""
        with self.cerrojo:
            return [dict(t) for t in self._trades]

    def locates(self) -> list[dict[str, Any]]:
        """Órdenes de locate: id, ticker, pedidas, abiertas, localizadas, precio, estado, ruta, hora, token."""
        with self.cerrojo:
            return [dict(loc) for loc in self._locates.values()]

    # ── privados (los usa el Emparejador, mismo módulo) ────────────────
    def _simbolo(self, ticker: str) -> dict[str, Any]:
        return self._simbolos.setdefault(ticker, {"ssr": False, "ta": None, "tat": None, "ld": None, "lu": None})

    def _cfg_locate(self, ticker: str) -> dict[str, Any]:
        return self._cfg_locates.setdefault(ticker, {
            "precio": PRECIO_LOCATE_SIMULADO, "disponibles": LOCATES_DISPONIBLES_SIMULADOS,
            "ruta": RUTA_LOCATE_SIMULADA, "tipo_ruta": 0, "reutilizable": True, "fallo": None,
        })

    def _tope_parcial(self, ticker: str, qty: int) -> Optional[int]:
        f = self._parcial_ticker.get(ticker, self._parcial_global)
        if f is None:
            return None
        return max(1, int((Decimal(qty) * f).to_integral_value(rounding=ROUND_FLOOR)))

    def _tomar_rechazo(self, accion: str, o: _OrdenSim) -> Optional[str]:
        for i, r in enumerate(self._rechazos):
            if r["accion"] == accion and r["token_o_orden"] in (None, o.token, o.id):
                del self._rechazos[i]
                return r["notas"]
        return None

    def _aplicar_fill(self, ticker: str, lado: str, qty: int, precio: Decimal, creada: str) -> Decimal:
        """Actualiza la posición y devuelve el P/L realizado de ESTE fill (media ponderada; giro de signo abre a `precio`)."""
        pos = self._pos.get(ticker)
        if pos is None:
            pos = self._pos[ticker] = {"neta": 0, "avg": Decimal("0"), "realizado": Decimal("0"), "tipo": 2,
                                       "creada": creada}
        neta = pos["neta"]
        delta = qty if lado == "B" else -qty
        pl = Decimal("0")
        nueva = neta + delta
        if neta == 0 or (neta > 0) == (delta > 0):
            if neta == 0:
                pos["creada"] = creada
            pos["avg"] = (pos["avg"] * abs(neta) + precio * qty) / abs(nueva)
        else:
            cierra = min(abs(neta), qty)
            pl = (precio - pos["avg"]) * cierra if neta > 0 else (pos["avg"] - precio) * cierra
            pos["realizado"] += pl
            if nueva == 0:
                pos["avg"] = Decimal("0")
            elif (nueva > 0) != (neta > 0):
                pos["avg"] = precio
                pos["creada"] = creada
        pos["neta"] = nueva
        if nueva > 0:
            pos["tipo"] = 2
        elif nueva < 0:
            pos["tipo"] = 3
        return pl

    def _no_realizado(self, ticker: str) -> Decimal:
        pos = self._pos.get(ticker)
        q = self._quotes.get(ticker)
        if pos is None or pos["neta"] == 0 or q is None or q.get("last") is None:
            return Decimal("0")
        return (q["last"] - pos["avg"]) * pos["neta"]


# ══════════════════════════════════════════════════════════════════════
# Emparejador: el motor de cruce
# ══════════════════════════════════════════════════════════════════════
class Emparejador:
    """Motor de cruce PURO salvo el reloj (§3.3): comando → líneas de respuesta. Lo usan el simulador y `ClienteSombra`.

    Parámetros de las variantes no documentadas (§5): `variante_order` 15 o
    19 campos; `tipo_stop_crudo` = prefijo del campo Type de un STOPLMTP en
    `%ORDER` («SLP» → «SLP: 2.97 2.99»; si lleva `{stop}`/`{precio}` se usa
    como plantilla); `replace_conserva_pp` (False → tras un REPLACE el tipo
    pasa a «SL: …»); `latencia_s` (la aplica `SimuladorDAS` antes de procesar
    un mutante); `qty_corto_negativa` (signo de `%POS` en cortos);
    `orden_mensajes` (permutación de "OrderAct", "TRADE", "POS" en cada
    fill; "OrderAct" incluye el `%ORDER` actualizado); `open_en_halt`
    ("aceptar" | "rechazar"); `replace_share_es_abierta` (A-02: True →
    `share` de un REPLACE = nueva cantidad ABIERTA; False → TOTAL, llenas +
    abierta, y un `share ≤ llenas` se rechaza con `ReplaceRej`).
    """

    def __init__(self, libro: LibroSimulado, reloj: Reloj, variante_order: int = 19, tipo_stop_crudo: str = "SLP",
                 replace_conserva_pp: bool = True, latencia_s: float = 0.0, qty_corto_negativa: bool = False,
                 orden_mensajes: tuple[str, ...] = ORDEN_MENSAJES_DEFECTO, open_en_halt: str = "aceptar",
                 replace_share_es_abierta: bool = REPLACE_SHARE_ES_ABIERTA) -> None:
        if not isinstance(libro, LibroSimulado):
            raise TypeError(f"libro debe ser un LibroSimulado: {libro!r}")
        if not callable(getattr(reloj, "ahora", None)):
            raise TypeError(f"reloj debe tener ahora(): {reloj!r}")
        if variante_order not in (15, 19) or type(variante_order) is not int:
            raise ValueError(f"variante_order debe ser 15 o 19: {variante_order!r}")
        if (not isinstance(tipo_stop_crudo, str) or not tipo_stop_crudo.strip()
                or any(c in tipo_stop_crudo for c in "\r\n")):
            raise ValueError(f"tipo_stop_crudo inválido: {tipo_stop_crudo!r}")
        if "{" in tipo_stop_crudo:
            try:
                tipo_stop_crudo.format(stop="1", precio="1")
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError(f"plantilla tipo_stop_crudo inválida: {tipo_stop_crudo!r}") from exc
        if isinstance(latencia_s, bool) or not isinstance(latencia_s, (int, float)) or not (0 <= latencia_s < 60):
            raise ValueError(f"latencia_s debe estar en [0, 60): {latencia_s!r}")
        orden = tuple(orden_mensajes)
        if sorted(orden) != sorted(ORDEN_MENSAJES_DEFECTO):
            raise ValueError(f"orden_mensajes debe ser una permutación de {ORDEN_MENSAJES_DEFECTO}: {orden_mensajes!r}")
        if open_en_halt not in OPEN_EN_HALT:
            raise ValueError(f"open_en_halt debe ser uno de {OPEN_EN_HALT}: {open_en_halt!r}")
        if not isinstance(replace_share_es_abierta, bool):
            raise ValueError(f"replace_share_es_abierta debe ser bool: {replace_share_es_abierta!r}")
        self._libro = libro
        self._reloj = reloj
        self.variante_order = variante_order
        self.tipo_stop_crudo = tipo_stop_crudo.strip()
        self.replace_conserva_pp = bool(replace_conserva_pp)
        self.latencia_s = float(latencia_s)
        self.qty_corto_negativa = bool(qty_corto_negativa)
        self.orden_mensajes = orden
        self.open_en_halt = open_en_halt
        self.replace_share_es_abierta = replace_share_es_abierta
        self._incidencias: list[str] = []
        self._manejadores = {
            "NEWORDER": self._neworder, "CANCEL": self._cancel, "REPLACE": self._replace,
            "SLPRICEINQUIRE": self._sl_inquire, "SLNEWORDER": self._sl_neworder,
            "SLOFFEROPERATION": self._sl_offer, "SLCANCELORDER": self._sl_cancel,
            "SLREUSEQUERY": self._sl_reuse, "SLAVAILQUERY": self._sl_avail, "SLROUTEMINCHARGE": self._sl_min_charge,
            "GET": self._get, "POSREFRESH": self._posrefresh,
        }

    @property
    def libro(self) -> LibroSimulado:
        return self._libro

    def incidencias(self) -> list[str]:
        """Comandos que no casaron con la gramática o no se pudieron aplicar (DAS no acusa la sintaxis, §5.15)."""
        with self._libro.cerrojo:
            return list(self._incidencias)

    # ── entradas ──────────────────────────────────────────────────────
    def recibir(self, linea: str) -> list[str]:
        """NEWORDER/CANCEL/REPLACE/SL*/GET/POSREFRESH → las líneas que DAS mandaría (§3.3, §4).

        La palabra clave no distingue mayúsculas. Una línea con saltos dentro
        son VARIOS comandos (como en el socket real). Un comando mal formado
        no produce nada y queda en `incidencias()`; uno válido pero
        inaceptable (fuera de tick, PostOnly que cruza, rechazo del guion)
        produce `Send_Rej`/`CancelRej`/`ReplaceRej` con su nota.
        """
        if not isinstance(linea, str):
            raise TypeError(f"recibir espera una línea de texto, no {type(linea).__name__}")
        salida: list[str] = []
        with self._libro.cerrojo:
            for trozo in linea.splitlines():
                texto = trozo.strip()
                if not texto:
                    continue
                palabras = texto.split()
                manejador = self._manejadores.get(palabras[0].upper())
                if manejador is None:
                    self._incidencias.append(f"comando no simulado: {texto}")
                    continue
                try:
                    salida.extend(manejador(palabras))
                except _ComandoMalo as exc:
                    self._incidencias.append(f"{exc}: {texto}")
        return salida

    def tic(self) -> list[str]:
        """Reaperturas pendientes (ruta OPEN al precio de `reabrir`), stops por último print y órdenes que reposan (§3.3)."""
        salida: list[str] = []
        with self._libro.cerrojo:
            for ticker, precio in list(self._libro._reaperturas.items()):
                del self._libro._reaperturas[ticker]
                salida.extend(self._llenar_reapertura(ticker, precio))
            for o in list(self._libro._ordenes.values()):
                if o.estado in _VIVAS:
                    salida.extend(self._intentar_llenar(o, agresiva=False))
        return salida

    def volcado(self) -> list[str]:
        """Lo que DAS manda tras el LOGIN (manual L250-255): `#POS…#POSEND`, `#Order…#OrderEnd`, `#Trade…#TradeEnd`."""
        with self._libro.cerrojo:
            return self._bloque_pos() + self._bloque_ordenes() + self._bloque_trades()

    # ── NEWORDER ──────────────────────────────────────────────────────
    def _neworder(self, p: list[str]) -> list[str]:
        """«NEWORDER token b/s symbol route share price|MKT|STOPLMTP stop price [PostOnly] TIF=… [Pref=…]» (L543-624)."""
        if len(p) < 7:
            raise _ComandoMalo("NEWORDER incompleto")
        token = _int32(p[1])
        lado = p[2].upper()
        if lado not in _LADOS_ORDEN:
            raise _ComandoMalo(f"lado desconocido {p[2]!r}")
        ticker, ruta = p[3], p[4]
        qty = _int(p[5])
        tif, pref, post_only, nucleo = "DAY", None, False, []
        for x in p[6:]:
            xu = x.upper()
            if xu.startswith("TIF="):
                tif = x[4:]
                if not tif:
                    raise _ComandoMalo("TIF vacío")
            elif xu.startswith("PREF="):
                pref = x[5:] or None
            elif xu == "POSTONLY":
                post_only = True
            else:
                nucleo.append(x)
        precio: Optional[Decimal] = None
        stop: Optional[Decimal] = None
        no_simulado = False
        if len(nucleo) == 1 and nucleo[0].upper() == "MKT":
            tipo = TipoOrden.MERCADO.value
        elif len(nucleo) == 1:
            tipo, precio = TipoOrden.LIMITE.value, _dec(nucleo[0])
        elif len(nucleo) == 3 and nucleo[0].upper() == "STOPLMTP":
            tipo, stop, precio = TipoOrden.STOP_LIMITE_PP.value, _dec(nucleo[1]), _dec(nucleo[2])
        elif nucleo and nucleo[0].upper() in _TIPOS_NO_SIMULADOS:
            tipo, no_simulado = nucleo[0].upper(), True
        else:
            raise _ComandoMalo("precio o tipo de orden ilegible")
        lib = self._libro
        o = _OrdenSim(id=lib._sig_orden, token=token, ticker=ticker, lado=lado, tipo=tipo, qty=qty, ruta=ruta,
                      tif=tif, pref=pref, post_only=post_only, precio=precio, stop=stop, lvqty=max(qty, 0),
                      tope_llenado=lib._tope_parcial(ticker, qty) if qty > 0 else None, hora=self._hora())
        lib._sig_orden += 1
        lib._ordenes[o.id] = o
        motivo = self._motivo_rechazo_nueva(o, no_simulado)
        salida = [self._orderact(o, EstadoOrden.SENDING.value, o.qty)]
        if motivo is not None:
            o.estado, o.lvqty = EstadoOrden.REJECTED.value, 0
            return salida + [self._orderact(o, "Send_Rej", o.qty, motivo), self._linea_orden(o)]
        o.estado = EstadoOrden.ACCEPTED.value
        salida += [self._orderact(o, "Accept", o.lvqty), self._linea_orden(o)]
        return salida + self._intentar_llenar(o, agresiva=True)

    def _motivo_rechazo_nueva(self, o: _OrdenSim, no_simulado: bool) -> Optional[str]:
        """Por qué DAS rechazaría esta orden (o None). El rechazo del guion se consume solo con una orden por lo demás válida."""
        if no_simulado:
            return NOTA_TIPO_NO_SIMULADO
        if o.qty <= 0:
            return NOTA_CANTIDAD
        for valor in (o.precio, o.stop):
            if valor is not None and not en_tick(valor):
                return NOTA_PRECIO
        if o.tipo == TipoOrden.STOP_LIMITE_PP.value and not _stop_coherente(o.lado, o.stop, o.precio):
            return NOTA_STOP
        if o.post_only and o.tipo != TipoOrden.LIMITE.value:
            return NOTA_POSTONLY_TIPO
        notas = self._libro._tomar_rechazo("Send_Rej", o)
        if notas is not None:
            return notas
        if self._libro.en_halt(o.ticker) and o.ruta.upper() == "OPEN" and self.open_en_halt == "rechazar":
            return NOTA_OPEN_HALT
        if o.post_only and self._cruzaria(o):
            return NOTA_POSTONLY
        return None

    def _cruzaria(self, o: _OrdenSim) -> bool:
        """¿Una límite cruzaría el libro al llegar? Compra: precio ≥ ask; venta/corto: precio ≤ bid."""
        q = self._libro._quotes.get(o.ticker)
        if q is None or o.precio is None:
            return False
        if o.lado == "B":
            return q["ask"] is not None and o.precio >= q["ask"]
        return q["bid"] is not None and o.precio <= q["bid"]

    # ── CANCEL ────────────────────────────────────────────────────────
    def _cancel(self, p: list[str]) -> list[str]:
        """«CANCEL orderid» / «CANCEL ALL» / «CANCEL ALLSYMB ticker» (L802-816, L226-229)."""
        if len(p) < 2:
            raise _ComandoMalo("CANCEL sin argumento")
        arg = p[1].upper()
        vivas = [o for o in self._libro._ordenes.values() if o.estado in _VIVAS]
        if arg == "ALL" and len(p) == 2:
            objetivo = vivas
        elif arg == "ALLSYMB" and len(p) == 3:
            objetivo = [o for o in vivas if o.ticker == p[2]]
        elif len(p) == 2:
            o = self._libro._ordenes.get(_int(p[1]))
            if o is None:
                raise _ComandoMalo(f"CANCEL de una orden desconocida {p[1]}")
            if o.estado not in _VIVAS:
                return [self._orderact(o, "CancelRej", o.lvqty, NOTA_NO_ABIERTA)]
            objetivo = [o]
        else:
            raise _ComandoMalo("CANCEL mal formado")
        salida: list[str] = []
        for o in objetivo:
            salida.extend(self._cancelar(o))
        return salida

    def _cancelar(self, o: _OrdenSim) -> list[str]:
        notas = self._libro._tomar_rechazo("CancelRej", o)
        if notas is not None:
            return [self._orderact(o, "CancelRej", o.lvqty, notas)]
        o.hora = self._hora()
        salida = [self._orderact(o, "Canceling", o.lvqty)]
        canceladas = o.lvqty
        o.cxlqty += canceladas
        o.lvqty = 0
        o.estado = EstadoOrden.CANCELED.value
        return salida + [self._orderact(o, "Canceled", canceladas), self._linea_orden(o)]

    # ── REPLACE ───────────────────────────────────────────────────────
    def _replace(self, p: list[str]) -> list[str]:
        """«REPLACE id share price» / «REPLACE id share STOPLMT stop price» / «REPLACE id share MKT» (L819-854; §5.6).

        `share` = nueva cantidad ABIERTA con `replace_share_es_abierta=True`
        (defecto) o TOTAL (llenas + abierta) con False (A-02: el manual no lo
        precisa). En el modo total, `share ≤ llenas` dejaría 0 abiertas o
        menos: `ReplaceRej` «Invalid quantity» (lo prudente: la orden sigue
        como estaba). Sobre un STOPLMTP, con `replace_conserva_pp=False` el
        tipo pasa a «SL: …» (así `tipo_conserva_pp` del decisor tiene algo que
        detectar, 2h.8).
        """
        if len(p) < 4:
            raise _ComandoMalo("REPLACE incompleto")
        o = self._libro._ordenes.get(_int(p[1]))
        if o is None:
            raise _ComandoMalo(f"REPLACE de una orden desconocida {p[1]}")
        share = _int(p[2])
        qty = share if self.replace_share_es_abierta else share - o.llenas     # nueva cantidad ABIERTA (A-02)
        resto = p[3:]
        nuevo_tipo: str
        precio: Optional[Decimal] = None
        stop: Optional[Decimal] = None
        if len(resto) == 1 and resto[0].upper() == "MKT":
            nuevo_tipo = TipoOrden.MERCADO.value
        elif len(resto) == 1:
            nuevo_tipo, precio = TipoOrden.LIMITE.value, _dec(resto[0])
        elif len(resto) == 3 and resto[0].upper() == "STOPLMT":
            nuevo_tipo, stop, precio = TipoOrden.STOP_LIMITE_PP.value, _dec(resto[1]), _dec(resto[2])
        else:
            raise _ComandoMalo("REPLACE mal formado")
        motivo = self._motivo_rechazo_replace(o, nuevo_tipo, qty, precio, stop)
        if motivo is not None:
            return [self._orderact(o, "ReplaceRej", o.lvqty, motivo)]
        salida = [self._orderact(o, "Replacing", o.lvqty)]
        o.lvqty = qty
        o.qty = o.llenas + qty
        o.tipo = nuevo_tipo
        o.hora = self._hora()
        if nuevo_tipo == TipoOrden.STOP_LIMITE_PP.value:
            if stop != o.stop:
                o.disparada = False
            o.stop = stop
            if not self.replace_conserva_pp:
                o.pp_perdido = True
        o.precio = precio
        salida += [self._orderact(o, "Replaced", o.lvqty), self._linea_orden(o)]
        return salida + self._intentar_llenar(o, agresiva=True)

    def _motivo_rechazo_replace(self, o: _OrdenSim, nuevo_tipo: str, qty: int, precio: Optional[Decimal],
                                stop: Optional[Decimal]) -> Optional[str]:
        if o.estado not in _VIVAS:
            return NOTA_NO_ABIERTA
        es_stop = o.tipo == TipoOrden.STOP_LIMITE_PP.value
        if es_stop != (nuevo_tipo == TipoOrden.STOP_LIMITE_PP.value):
            return NOTA_TIPO_REPLACE
        if qty <= 0:
            return NOTA_CANTIDAD
        for valor in (precio, stop):
            if valor is not None and not en_tick(valor):
                return NOTA_PRECIO
        if es_stop and not _stop_coherente(o.lado, stop, precio):
            return NOTA_STOP
        if o.post_only and nuevo_tipo != TipoOrden.LIMITE.value:
            return NOTA_POSTONLY_TIPO
        notas = self._libro._tomar_rechazo("ReplaceRej", o)
        if notas is not None:
            return notas
        if o.post_only:
            q = self._libro._quotes.get(o.ticker)
            if q is not None and precio is not None and (
                    (o.lado == "B" and q["ask"] is not None and precio >= q["ask"])
                    or (o.lado != "B" and q["bid"] is not None and precio <= q["bid"])):
                return NOTA_POSTONLY
        return None

    # ── cruce ─────────────────────────────────────────────────────────
    def _intentar_llenar(self, o: _OrdenSim, agresiva: bool) -> list[str]:
        """Reglas de cruce de §3.3. `agresiva` = recién llegada, reemplazada o stop recién disparado: se llena al toque.

        Una orden que reposa se llena a SU precio (liquidez añadida). Nada se
        llena en halt. El tamaño del libro se consume.
        """
        if o.estado not in _VIVAS or self._libro.en_halt(o.ticker):
            return []
        q = self._libro._quotes.get(o.ticker)
        if q is None:
            return []
        compra = o.lado == "B"
        if o.tipo == TipoOrden.STOP_LIMITE_PP.value and not o.disparada:
            ultimo = q.get("last")
            if ultimo is None or not ((compra and ultimo >= o.stop) or (not compra and ultimo <= o.stop)):
                return []
            o.disparada = True
            agresiva = True
        toque = q["ask"] if compra else q["bid"]
        if toque is None:
            return []
        if o.tipo == TipoOrden.MERCADO.value:
            precio = toque
            agresiva = True
        else:
            if not ((compra and toque <= o.precio) or (not compra and toque >= o.precio)):
                return []
            precio = toque if agresiva else o.precio
        clave_tamano = "tamano_ask" if compra else "tamano_bid"
        cantidad = self._cantidad_llenable(o, q[clave_tamano])
        if cantidad <= 0:
            return []
        if q[clave_tamano] is not None:
            q[clave_tamano] -= cantidad
        return self._ejecutar(o, cantidad, precio, "-" if agresiva else "+")

    def _llenar_reapertura(self, ticker: str, precio: Decimal) -> list[str]:
        """EP-2: las órdenes vivas por ruta OPEN del ticker se llenan al precio de reapertura (subasta: sin tope de libro)."""
        salida: list[str] = []
        for o in list(self._libro._ordenes.values()):
            if o.ticker != ticker or o.estado not in _VIVAS or o.ruta.upper() != "OPEN":
                continue
            compra = o.lado == "B"
            if o.tipo == TipoOrden.STOP_LIMITE_PP.value and not o.disparada:
                if not ((compra and precio >= o.stop) or (not compra and precio <= o.stop)):
                    continue
                o.disparada = True
            if o.tipo != TipoOrden.MERCADO.value and not (
                    (compra and precio <= o.precio) or (not compra and precio >= o.precio)):
                continue
            cantidad = self._cantidad_llenable(o, None)
            if cantidad > 0:
                salida.extend(self._ejecutar(o, cantidad, precio, "-"))
        return salida

    @staticmethod
    def _cantidad_llenable(o: _OrdenSim, tamano_libro: Optional[int]) -> int:
        cantidad = o.lvqty
        if o.tope_llenado is not None:
            cantidad = min(cantidad, o.tope_llenado - o.llenas)
        if tamano_libro is not None:
            cantidad = min(cantidad, tamano_libro)
        return cantidad

    def _ejecutar(self, o: _OrdenSim, cantidad: int, precio: Decimal, liq: str) -> list[str]:
        """Un fill: orden, trade y posición; líneas en el orden de `orden_mensajes` (§5.12, riesgo 8)."""
        lib = self._libro
        hora = self._hora()
        o.llenas += cantidad
        o.lvqty -= cantidad
        o.hora = hora
        o.estado = EstadoOrden.EXECUTED.value if o.lvqty == 0 else EstadoOrden.PARTIAL.value
        pl = lib._aplicar_fill(o.ticker, o.lado, cantidad, precio, self._creada())
        trade = {"id": lib._sig_trade, "ticker": o.ticker, "lado": o.lado, "qty": cantidad, "precio": precio,
                 "ruta": o.ruta, "hora": hora, "id_orden": o.id, "token": o.token, "liq": liq, "pl": pl}
        lib._sig_trade += 1
        lib._trades.append(trade)
        grupos = {
            "OrderAct": [self._orderact(o, "Execute", cantidad, precio=precio), self._linea_orden(o)],
            "TRADE": [self._linea_trade(trade)],
            "POS": [self._linea_pos(o.ticker)],
        }
        salida: list[str] = []
        for nombre in self.orden_mensajes:
            salida.extend(grupos[nombre])
        return salida

    # ── locates (L1648-1838) ──────────────────────────────────────────
    def _sl_inquire(self, p: list[str]) -> list[str]:
        """«SLPRICEINQUIRE Symbol LocateShares Route|ALLROUTE|ALLROUTEWTTYPE1» → `%SLRET` (o `%SLOrder Offered` con ALLROUTE en tipo 1, §5.22)."""
        if len(p) != 4:
            raise _ComandoMalo("SLPRICEINQUIRE mal formado")
        ticker, qty, ruta = p[1], _int(p[2]), p[3]
        cfg = self._libro._cfg_locate(ticker)
        if cfg["fallo"] is not None:
            return [self._slret(2, ticker, Decimal("0"), 0, cfg["ruta"], cfg["fallo"])]
        if cfg["tipo_ruta"] == 1:
            if ruta.upper() == "ALLROUTE":
                return [self._linea_slorder(self._nuevo_locate(ticker, qty, cfg, token=None))]
            if ruta.upper() != "ALLROUTEWTTYPE1":
                return [self._slret(2, ticker, Decimal("0"), 0, cfg["ruta"], NOTA_LOCATE_TIPO1)]
            return [self._slret(1, ticker, Decimal("0"), 0, cfg["ruta"], "")]
        return [self._slret(1, ticker, cfg["precio"], min(qty, cfg["disponibles"]) if qty > 0 else 0, cfg["ruta"], "")]

    def _sl_neworder(self, p: list[str]) -> list[str]:
        """«SLNEWORDER Symbol LocateShares Route token [Price]» → `%SLOrder` Pending y luego Located/Rejected (tipo 0) u Offered (tipo 1)."""
        if len(p) not in (5, 6):
            raise _ComandoMalo("SLNEWORDER mal formado")
        ticker, qty, token = p[1], _int(p[2]), _int32(p[4])
        if len(p) == 6:
            _dec(p[5])
        cfg = self._libro._cfg_locate(ticker)
        if cfg["fallo"] is not None:
            return [self._slret(2, ticker, Decimal("0"), 0, cfg["ruta"], cfg["fallo"])]
        if qty <= 0:
            raise _ComandoMalo("SLNEWORDER con cantidad ≤ 0")
        loc = self._nuevo_locate(ticker, qty, cfg, token=token)
        if cfg["tipo_ruta"] == 1:
            return [self._linea_slorder(loc)]
        salida = [self._linea_slorder(dict(loc, estado="Pending"))]
        self._localizar(loc, cfg)
        return salida + [self._linea_slorder(loc)]

    def _nuevo_locate(self, ticker: str, qty: int, cfg: dict[str, Any], token: Optional[int]) -> dict[str, Any]:
        lib = self._libro
        loc = {"id": lib._sig_locate, "ticker": ticker, "pedidas": qty, "abiertas": qty, "localizadas": 0,
               "precio": cfg["precio"], "estado": "Offered" if cfg["tipo_ruta"] == 1 else "Pending",
               "ruta": cfg["ruta"], "hora": self._hora(), "token": token}
        lib._sig_locate += 1
        lib._locates[loc["id"]] = loc
        return loc

    def _localizar(self, loc: dict[str, Any], cfg: dict[str, Any]) -> None:
        cantidad = min(loc["abiertas"], cfg["disponibles"])
        cfg["disponibles"] -= cantidad
        loc["localizadas"] += cantidad
        loc["abiertas"] -= cantidad
        loc["estado"] = "Located" if cantidad > 0 else "Rejected"
        loc["hora"] = self._hora()

    def _sl_offer(self, p: list[str]) -> list[str]:
        """«SLOFFEROPERATION locateOrderId Accept|Reject» (L1692-1700): Offered → Located | Closed."""
        if len(p) != 3 or p[2].upper() not in ("ACCEPT", "REJECT"):
            raise _ComandoMalo("SLOFFEROPERATION mal formado")
        loc = self._libro._locates.get(_int(p[1]))
        if loc is None or loc["estado"] != "Offered":
            raise _ComandoMalo(f"SLOFFEROPERATION sobre un locate que no está Offered: {p[1]}")
        if p[2].upper() == "ACCEPT":
            self._localizar(loc, self._libro._cfg_locate(loc["ticker"]))
        else:
            loc["estado"] = "Closed"
            loc["hora"] = self._hora()
        return [self._linea_slorder(loc)]

    def _sl_cancel(self, p: list[str]) -> list[str]:
        """«SLCANCELORDER locateOrderId» (L1686-1691): solo un locate abierto (Pending/Waiting/Offered) pasa a Canceled."""
        if len(p) != 2:
            raise _ComandoMalo("SLCANCELORDER mal formado")
        loc = self._libro._locates.get(_int(p[1]))
        if loc is None or loc["estado"] not in ("Pending", "Waiting", "Offered"):
            raise _ComandoMalo(f"SLCANCELORDER sobre un locate que no está abierto: {p[1]}")
        loc["estado"] = "Canceled"
        loc["hora"] = self._hora()
        return [self._linea_slorder(loc)]

    def _sl_reuse(self, p: list[str]) -> list[str]:
        """«SLReuseQuery Symbol|ALL» → `$SLReuseQueryRet Symbol Yes/No` (L1810-1822, EP-9)."""
        if len(p) != 2:
            raise _ComandoMalo("SLReuseQuery mal formado")
        if p[1].upper() == "ALL":
            return [f"$SLReuseQueryRet {t} No" for t, cfg in self._libro._cfg_locates.items() if not cfg["reutilizable"]]
        cfg = self._libro._cfg_locate(p[1])
        return [f"$SLReuseQueryRet {p[1]} {'Yes' if cfg['reutilizable'] else 'No'}"]

    def _sl_avail(self, p: list[str]) -> list[str]:
        """«SLAvailQuery Account Symbol» → `$SLAvailQueryRet Account Symbol N` (L1796-1809)."""
        if len(p) != 3:
            raise _ComandoMalo("SLAvailQuery mal formado")
        return [f"$SLAvailQueryRet {p[1]} {p[2]} {self._libro._cfg_locate(p[2])['disponibles']}"]

    def _sl_min_charge(self, p: list[str]) -> list[str]:
        """«SLRouteMinCharge Route|ALLROUTE» → `SLRouteMinChargeRet Route minimo` (L1823-1838; sin `$`, como el ejemplo)."""
        if len(p) != 2:
            raise _ComandoMalo("SLRouteMinCharge mal formado")
        cargos = self._libro._min_charge
        if p[1].upper() == "ALLROUTE":
            return [f"SLRouteMinChargeRet {r} {_num(m)}" for r, m in cargos.items()]
        return [f"SLRouteMinChargeRet {p[1]} {_num(cargos.get(p[1], Decimal('0')))}"]

    # ── GET (L988-1170) ───────────────────────────────────────────────
    def _get(self, p: list[str]) -> list[str]:
        """Respuestas plausibles a los GET que usa el bot; un GET desconocido no responde nada (queda en incidencias)."""
        if len(p) < 2:
            raise _ComandoMalo("GET sin nombre")
        nombre = p[1].upper()
        arg = p[2] if len(p) > 2 else None
        lib = self._libro
        if nombre == "BP":
            return ["#buyingpower bp,nbp", f"BP {_num(lib.bp)} {_num(lib.bp_overnight)}"]
        if nombre == "POSITIONS":
            return self._bloque_pos()
        if nombre == "ORDERS":
            return self._bloque_ordenes()
        if nombre == "TRADES":
            return self._bloque_trades()
        if nombre == "LOCATES":
            return [CABECERA_SLORDER] + [self._linea_slorder(loc) for loc in lib._locates.values()] + ["#SLOrderEnd"]
        if nombre == "SYMSTATUS":
            tickers = [arg] if arg else sorted(set(lib._simbolos) | set(lib._quotes))
            return [self._linea_symstatus(t) for t in tickers]
        if nombre == "LDLU":
            tickers = [arg] if arg else sorted(lib._simbolos)
            return [f"$LDLU {t} {_num(s['ld'])} {_num(s['lu'])}" for t in tickers
                    if (s := lib._simbolos.get(t)) is not None and s["ld"] is not None]
        if nombre == "SHORTINFO":
            if arg is None:
                raise _ComandoMalo("GET SHORTINFO sin símbolo")
            return [f"$SHORTINFO {arg} Y 100000 Y 0 0 N N"]
        if nombre == "ACCOUNTINFO":
            realizado = sum((pos["realizado"] for pos in lib._pos.values()), Decimal("0"))
            no_realizado = sum((lib._no_realizado(t) for t in lib._pos), Decimal("0"))
            neto = realizado + no_realizado
            numeros = [lib.equity_inicial, lib.equity_inicial + neto, realizado, no_realizado, neto] + [Decimal("0")] * 5
            return ["$AccountInfo " + " ".join(_num(x, 2) for x in numeros)]
        if nombre == "ROUTESTATUS":
            return [f"$RouteStatus {r} {'Enabled' if activa else 'Disabled'}" for r, activa in lib.rutas.items()]
        if nombre == "INTMSGS":
            return []
        raise _ComandoMalo(f"GET no simulado {p[1]!r}")

    def _posrefresh(self, p: list[str]) -> list[str]:
        """«POSREFRESH» (L326-330): la lista de posiciones entera."""
        return self._bloque_pos()

    # ── formato de líneas ─────────────────────────────────────────────
    def _bloque_pos(self) -> list[str]:
        return [CABECERA_POS] + [self._linea_pos(t) for t in self._libro._pos] + ["#POSEND"]

    def _bloque_ordenes(self) -> list[str]:
        cabecera = CABECERA_ORDER_19 if self.variante_order == 19 else CABECERA_ORDER_15
        return [cabecera] + [self._linea_orden(o) for o in self._libro._ordenes.values()] + ["#OrderEnd"]

    def _bloque_trades(self) -> list[str]:
        return [CABECERA_TRADE] + [self._linea_trade(t) for t in self._libro._trades] + ["#TradeEnd"]

    def _tipo_crudo(self, o: _OrdenSim) -> str:
        """Campo Type de `%ORDER` (§5.2): «L», «MKT» o el del STOPLMTP según `tipo_stop_crudo` / `replace_conserva_pp`."""
        if o.tipo == TipoOrden.LIMITE.value:
            return "L"
        if o.tipo == TipoOrden.STOP_LIMITE_PP.value and o.stop is not None and o.precio is not None:
            prefijo = "SL" if o.pp_perdido else self.tipo_stop_crudo
            if "{" in prefijo:
                return prefijo.format(stop=_num(o.stop), precio=_num(o.precio))
            return f"{prefijo}: {_num(o.stop)} {_num(o.precio)}"
        return o.tipo

    def _linea_orden(self, o: _OrdenSim) -> str:
        """`%ORDER` de 15 o 19 campos (L343-352, L930-932)."""
        campos = [str(o.id), str(o.token), o.ticker, o.lado, self._tipo_crudo(o), str(o.qty), str(o.lvqty),
                  str(o.cxlqty), _num(o.precio) if o.precio is not None else "0", o.ruta, o.estado, o.hora, "0",
                  self._libro.cuenta, self._libro.trader]
        if self.variante_order == 19:
            campos += ["CMDAPI", o.tif, o.pref or "N/A"]
        return "%ORDER " + " ".join(campos)

    def _orderact(self, o: _OrdenSim, accion: str, qty: int, notas: str = "",
                  precio: Optional[Decimal] = None) -> str:
        """`%OrderAct id ActionType B/S symbol qty price route time notes token` (L434-494): notas vacías = dos espacios."""
        valor = precio if precio is not None else o.precio
        return (f"%OrderAct {o.id} {accion} {_LADO_ORDERACT.get(o.lado, o.lado)} {o.ticker} {qty} "
                f"{_num(valor) if valor is not None else '0'} {o.ruta} {self._hora()} {notas} {o.token}")

    def _linea_trade(self, t: dict[str, Any]) -> str:
        """`%TRADE id symb b/s qty price route time orderid Liq EcnFee PL` (11 campos, L505-513)."""
        return (f"%TRADE {t['id']} {t['ticker']} {t['lado']} {t['qty']} {_num(t['precio'])} {t['ruta']} {t['hora']} "
                f"{t['id_orden']} {t['liq']} 0 {_num(t['pl'], 2)}")

    def _linea_pos(self, ticker: str) -> str:
        """`%POS Symbol Type Quantity AvgCost InitQuantity InitPrice Realized CreateTime Unrealized` (L256-281).

        Con `qty_corto_negativa` el corto sale con signo menos; si no, en
        valor absoluto (§5.12: el signo no está documentado).
        """
        pos = self._libro._pos[ticker]
        neta = pos["neta"]
        qty = neta if (neta < 0 and self.qty_corto_negativa) else abs(neta)
        return (f"%POS {ticker} {pos['tipo']} {qty} {_num(pos['avg'], 4)} 0 0 {_num(pos['realizado'], 2)} "
                f"{pos['creada']} {_num(self._libro._no_realizado(ticker), 2)}")

    def _linea_slorder(self, loc: dict[str, Any]) -> str:
        """`%SLOrder id symb shares openshares exeshares exeprice status route time lmtPrice [token] notes` (L1766-1795)."""
        token = f" {loc['token']}" if loc.get("token") is not None else ""
        return (f"%SLOrder {loc['id']} {loc['ticker']} {loc['pedidas']} {loc['abiertas']} {loc['localizadas']} "
                f"{_num(loc['precio'])} {loc['estado']} {loc['ruta']} {loc['hora']} 0{token}")

    def _slret(self, tipo: int, ticker: str, precio: Decimal, tamano: int, ruta: str, notas: str) -> str:
        """`%SLRET RetType Symbol OfferPrice OfferSize Route Notes Account` (L1701-1720): notas vacías = dos espacios."""
        return f"%SLRET {tipo} {ticker} {_num(precio)} {tamano} {ruta} {notas} {self._libro.cuenta}"

    def _linea_symstatus(self, ticker: str) -> str:
        """`$IssueStatus symbol SSR:Y/N [TA:x TAT:HH:MM:SS]` (L1101-1133): sin TA = normal."""
        simb = self._libro._simbolos.get(ticker, {})
        linea = f"$IssueStatus {ticker} SSR:{'Y' if simb.get('ssr') else 'N'}"
        if simb.get("ta"):
            linea += f" TA:{simb['ta']}"
            if simb.get("tat"):
                linea += f" TAT:{simb['tat']}"
        return linea

    def _hora(self) -> str:
        return self._reloj.ahora().strftime("%H:%M:%S")

    def _creada(self) -> str:
        return self._reloj.ahora().strftime("%Y/%m/%d-%H:%M:%S")


# ══════════════════════════════════════════════════════════════════════
# Servidor TCP
# ══════════════════════════════════════════════════════════════════════
class _Conexion:
    """Un cliente conectado: socket, si está logueado, si es watch y sus suscripciones Lv1."""

    def __init__(self, sock: socket.socket, numero: int) -> None:
        self.sock = sock
        self.numero = numero
        self.logueado = False
        self.watch = False
        self.suscripciones: set[str] = set()
        self.viva = True
        self.cerrojo_envio = threading.Lock()
        self.hilo: Optional[threading.Thread] = None


class SimuladorDAS:
    """Servidor TCP que habla el CMD API (§3.3, §4): N conexiones normales y watch; LOGIN → volcado.

    `usuarios` = {usuario: clave} inventados por el test; None acepta
    cualquier LOGIN. `emparejador` opcional (por defecto uno con las
    variantes por defecto sobre `libro`). `fin_linea` ("\\r\\n" por defecto)
    se puede cambiar a "\\n" para probar el lector del cliente.
    """

    def __init__(self, libro: LibroSimulado, reloj: Reloj, host: str = "127.0.0.1", puerto: int = 0,
                 usuarios: Optional[dict[str, str]] = None, emparejador: Optional[Emparejador] = None,
                 dormir: Optional[Callable[[float], None]] = None) -> None:
        # R2-RED-2: `dormir` (por defecto `time.sleep`) es quien aplica la `latencia_s`
        # del emparejador antes de procesar un mutante; los tests lo inyectan para
        # comprobar la latencia por el orden de los eventos, sin reloj de pared.
        if dormir is not None and not callable(dormir):
            raise TypeError(f"dormir debe ser invocable: {dormir!r}")
        if not isinstance(libro, LibroSimulado):
            raise TypeError(f"libro debe ser un LibroSimulado: {libro!r}")
        if emparejador is None:
            emparejador = Emparejador(libro, reloj)
        elif not isinstance(emparejador, Emparejador) or emparejador.libro is not libro:
            raise ValueError("el emparejador debe ser un Emparejador sobre el MISMO libro")
        if type(puerto) is not int or not (0 <= puerto <= 65535):
            raise ValueError(f"puerto inválido: {puerto!r}")
        if usuarios is not None and (not isinstance(usuarios, dict)
                                     or not all(isinstance(k, str) and isinstance(v, str) for k, v in usuarios.items())):
            raise ValueError("usuarios debe ser un dict {usuario: clave} de textos")
        self._libro = libro
        self._reloj = reloj
        self._host = host
        self._puerto = puerto
        self._usuarios = dict(usuarios) if usuarios is not None else None
        self._emparejador = emparejador
        self._dormir: Callable[[float], None] = dormir if dormir is not None else time.sleep
        self.fin_linea = FIN_LINEA
        self._cerrojo = threading.RLock()          # emisión ordenada: mismas líneas, mismo orden, en todas las conexiones
        self._conexiones: list[_Conexion] = []
        self._recibidas: list[str] = []
        self._errores: list[str] = []
        self._escucha: Optional[socket.socket] = None
        self._hilo_escucha: Optional[threading.Thread] = None
        self._parando = threading.Event()
        self._direccion: Optional[tuple[str, int]] = None
        self._numero = 0

    # ── propiedades ───────────────────────────────────────────────────
    @property
    def libro(self) -> LibroSimulado:
        return self._libro

    @property
    def emparejador(self) -> Emparejador:
        return self._emparejador

    @property
    def direccion(self) -> Optional[tuple[str, int]]:
        return self._direccion

    @property
    def n_conexiones(self) -> int:
        """Conexiones abiertas y logueadas."""
        with self._cerrojo:
            return sum(1 for c in self._conexiones if c.viva and c.logueado)

    # ── ciclo de vida ─────────────────────────────────────────────────
    def arrancar(self) -> tuple[str, int]:
        """Abre el puerto (0 = el que dé el sistema) y el hilo que acepta; devuelve (host, puerto). Idempotente."""
        with self._cerrojo:
            if self._direccion is not None and not self._parando.is_set():
                return self._direccion
            self._parando.clear()
            escucha = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                escucha.bind((self._host, self._puerto))
                escucha.listen(8)
                escucha.settimeout(_TIMEOUT_SOCKET_S)
            except OSError:
                escucha.close()
                raise
            self._escucha = escucha
            host, puerto = escucha.getsockname()[:2]
            self._direccion = (host, puerto)
            self._hilo_escucha = threading.Thread(target=self._aceptar, name="simdas-escucha", daemon=True)
            self._hilo_escucha.start()
            return self._direccion

    def parar(self) -> None:
        """Cierra el puerto y todas las conexiones y une los hilos (con plazo). Idempotente."""
        self._parando.set()
        with self._cerrojo:
            escucha, self._escucha = self._escucha, None
            conexiones = list(self._conexiones)
        if escucha is not None:
            try:
                escucha.close()
            except OSError:
                pass
        for c in conexiones:
            self._cerrar_conexion(c)
        hilos = [self._hilo_escucha] + [c.hilo for c in conexiones]
        for hilo in hilos:
            if hilo is not None and hilo is not threading.current_thread():
                hilo.join(_ESPERA_UNION_S)

    def cortar(self, cual: str = "todas") -> None:
        """Simula la caída de DAS (R-J-02): EOF en las conexiones `cual` ∈ todas | normal | watch. El puerto sigue abierto."""
        if cual not in CORTES:
            raise ValueError(f"cortar: {cual!r} no es uno de {CORTES}")
        with self._cerrojo:
            objetivo = [c for c in self._conexiones
                        if cual == "todas" or (cual == "watch") == c.watch]
        for c in objetivo:
            self._cerrar_conexion(c)

    # ── inyección y observación ───────────────────────────────────────
    def emitir(self, linea: str, a_watch: bool = False) -> None:
        """Manda `linea` (+ `fin_linea`) a todas las conexiones logueadas normales (o watch con `a_watch`)."""
        if not isinstance(linea, str):
            raise TypeError("emitir espera texto")
        with self._cerrojo:
            for c in self._logueadas():
                if c.watch == a_watch:
                    self._enviar(c, [linea])

    def emitir_crudo(self, datos: bytes | str, a_watch: bool = False) -> None:
        """Manda bytes TAL CUAL (sin fin de línea): para partir una línea en varios `recv` del cliente."""
        if isinstance(datos, str):
            datos = datos.encode(CODIFICACION, errors="replace")
        if not isinstance(datos, (bytes, bytearray)):
            raise TypeError("emitir_crudo espera bytes o texto")
        with self._cerrojo:
            for c in self._logueadas():
                if c.watch == a_watch:
                    self._enviar_bytes(c, bytes(datos))

    def recibidas(self) -> list[str]:
        """Todas las líneas que llegaron al simulador (todas las conexiones, en orden, sin fin de línea)."""
        with self._cerrojo:
            return list(self._recibidas)

    def errores(self) -> list[str]:
        """Trazas de excepciones internas del simulador al procesar una línea (un test sano las deja vacías)."""
        with self._cerrojo:
            return list(self._errores)

    def esperar_logueadas(self, n: int = 1, watch: Optional[bool] = None, timeout_s: float = 2.0) -> bool:
        """Espera (sondeo cada 10 ms) a que haya `n` conexiones logueadas (del tipo pedido); False si vence el plazo."""
        limite = time.monotonic() + timeout_s
        while True:
            with self._cerrojo:
                cuantas = sum(1 for c in self._logueadas() if watch is None or c.watch == watch)
            if cuantas >= n:
                return True
            if time.monotonic() >= limite:
                return False
            time.sleep(0.01)

    # ── mercado desde el test o el replay ─────────────────────────────
    def cotizar(self, ticker: str, bid: Decimal, ask: Decimal, last: Optional[Decimal] = None, volumen: int = 0,
                vwap: Optional[Decimal] = None, tamano_bid: Optional[int] = None,
                tamano_ask: Optional[int] = None) -> list[str]:
        """`libro.cotizar` + `$Quote` a los suscritos + `tic()`; devuelve todo lo emitido."""
        with self._cerrojo:
            lineas = self._libro.cotizar(ticker, bid, ask, last=last, volumen=volumen, vwap=vwap,
                                         tamano_bid=tamano_bid, tamano_ask=tamano_ask)
            self._repartir_quote(ticker, lineas)
            return lineas + self.tic()

    def desde_vela(self, ticker: str, vela: dict, spread: ModeloSpread) -> list[str]:
        """`libro.desde_vela` + `$Quote` a los suscritos + `tic()` (replay, injerto A §8.24)."""
        with self._cerrojo:
            lineas = self._libro.desde_vela(ticker, vela, spread)
            self._repartir_quote(ticker, lineas)
            return lineas + self.tic()

    def reabrir(self, ticker: str, precio: Decimal, tat: Optional[str] = None) -> list[str]:
        """`libro.reabrir` + `tic()`: las órdenes por ruta OPEN se llenan al precio de reapertura (EP-2)."""
        with self._cerrojo:
            self._libro.reabrir(ticker, precio, tat=tat)
            return self.tic()

    def tic(self) -> list[str]:
        """`emparejador.tic()` y difusión de lo que produzca."""
        with self._cerrojo:
            lineas = self._emparejador.tic()
            self._distribuir(lineas, None)
            return lineas

    # ── privados: red ─────────────────────────────────────────────────
    def _aceptar(self) -> None:
        while not self._parando.is_set():
            escucha = self._escucha
            if escucha is None:
                return
            try:
                sock, _origen = escucha.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            sock.settimeout(_TIMEOUT_SOCKET_S)
            with self._cerrojo:
                if self._parando.is_set():
                    sock.close()
                    return
                self._numero += 1
                conexion = _Conexion(sock, self._numero)
                conexion.hilo = threading.Thread(target=self._atender, args=(conexion,),
                                                 name=f"simdas-conexion-{self._numero}", daemon=True)
                self._conexiones.append(conexion)
            conexion.hilo.start()

    def _atender(self, c: _Conexion) -> None:
        buffer = b""
        try:
            with self._cerrojo:
                self._enviar(c, list(BIENVENIDA))            # el DAS real saluda nada más aceptar (01-oct)
            while c.viva and not self._parando.is_set():
                try:
                    datos = c.sock.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not datos:
                    break
                buffer += datos
                while b"\n" in buffer and c.viva:
                    cruda, _separador, buffer = buffer.partition(b"\n")
                    linea = cruda.rstrip(b"\r").decode(CODIFICACION, errors="replace")
                    try:
                        self._procesar(c, linea)
                    except Exception:  # noqa: BLE001 — frontera de mensaje: un fallo del simulador no tumba la conexión; queda en errores()
                        with self._cerrojo:
                            self._errores.append(traceback.format_exc())
        finally:
            self._cerrar_conexion(c)

    def _procesar(self, c: _Conexion, linea: str) -> None:
        with self._cerrojo:
            self._recibidas.append(linea)
        texto = linea.strip()
        if not texto:
            return
        p = texto.split()
        clave = p[0].upper()
        if clave == "LOGIN":
            self._login(c, p)
            return
        if not c.logueado:
            return                                    # sin LOGIN, DAS no documenta respuesta: se ignora
        if clave == "QUIT":
            self._cerrar_conexion(c)
            return
        with self._cerrojo:
            if clave in ("SB", "UNSB"):
                self._suscripcion(c, p, alta=(clave == "SB"))
            elif clave == "RETURNFULLLV1":
                return
            elif clave == "ECHO":
                self._enviar(c, [f"ECHO {p[1].upper() if len(p) > 1 and p[1].upper() in ('ON', 'OFF') else 'ON'}"])
            elif clave == "CLIENT":
                self._enviar(c, [f"CLIENT {sum(1 for x in self._logueadas())}"])
            elif clave in ("GET", "POSREFRESH"):
                self._enviar(c, self._emparejador.recibir(texto))
            else:
                if self._emparejador.latencia_s > 0:
                    self._dormir(self._emparejador.latencia_s)
                self._distribuir(self._emparejador.recibir(texto), c)

    def _login(self, c: _Conexion, p: list[str]) -> None:
        """«LOGIN Trader Password Account 1/0» (L243-255): 1 = watch. Como el DAS real (01-oct): éxito → «#LOGIN
        SUCCESSED» + estados de conexión + volcado; fallo → «ERROR:INVALID PASSWORD» (la conexión sigue abierta)."""
        ok = len(p) >= 4 and (self._usuarios is None or self._usuarios.get(p[1]) == p[2])
        with self._cerrojo:
            if not ok:
                self._enviar(c, [LOGIN_RECHAZADO])
                return
            c.logueado = True
            c.watch = len(p) > 4 and p[4] == "1"
            volcado = self._emparejador.volcado()
            if c.watch:
                volcado = [self._a_watch(x) or x for x in volcado]
            self._enviar(c, [LOGIN_ACEPTADO, "#OrderServer:Logon:Successful", "#QuoteServer:Logon:Successful"]
                         + volcado)

    def _suscripcion(self, c: _Conexion, p: list[str], alta: bool) -> None:
        if len(p) < 2:
            return
        canal = p[2].upper() if len(p) > 2 else "LV1"
        if canal != "LV1":
            return                                    # tms/Lv2 no se simulan (el bot no los usa, R-A-06)
        ticker = p[1]
        if alta:
            c.suscripciones.add(ticker)
            if self._libro.cotizacion(ticker) is not None:
                self._enviar(c, [self._libro.linea_quote(ticker)])
        else:
            c.suscripciones.discard(ticker)

    def _repartir_quote(self, ticker: str, lineas: list[str]) -> None:
        for c in self._logueadas():
            if ticker in c.suscripciones:
                self._enviar(c, lineas)

    def _distribuir(self, lineas: list[str], solicitante: Optional[_Conexion]) -> None:
        """Eventos de órdenes/locates → a TODAS las normales (y en su forma %I… a las watch); el resto → solo al que preguntó."""
        if not lineas:
            return
        for c in self._logueadas():
            if c is solicitante:
                salida = [(self._a_watch(x) or x) if c.watch else x for x in lineas]
            elif c.watch:
                salida = [w for x in lineas if _es_evento(x) and (w := self._a_watch(x)) is not None]
            else:
                salida = [x for x in lineas if _es_evento(x)]
            self._enviar(c, salida)

    def _a_watch(self, linea: str) -> Optional[str]:
        """%ORDER → %IORDER, %POS → %IPOS, %TRADE → %ITRADE (orden de campos PROPIO, L1446-1458); lo demás → None."""
        palabra, _separador, resto = linea.partition(" ")
        clave = palabra.upper()
        if clave == "%ORDER":
            return f"%IORDER {resto}"
        if clave == "%POS":
            return f"%IPOS {resto}"
        if clave == "%TRADE":
            c = resto.split()
            if len(c) < 8:
                return None
            return f"%ITRADE {self._libro.cuenta} {' '.join(c[:8])} {self._libro.trader}"
        return None

    def _logueadas(self) -> list[_Conexion]:
        return [c for c in self._conexiones if c.viva and c.logueado]

    def _enviar(self, c: _Conexion, lineas: list[str]) -> None:
        if lineas:
            self._enviar_bytes(c, "".join(x + self.fin_linea for x in lineas).encode(CODIFICACION, errors="replace"))

    def _enviar_bytes(self, c: _Conexion, datos: bytes) -> None:
        if not c.viva:
            return
        try:
            with c.cerrojo_envio:
                c.sock.sendall(datos)
        except OSError:
            self._cerrar_conexion(c)

    def _cerrar_conexion(self, c: _Conexion) -> None:
        with self._cerrojo:
            c.viva = False
            if c in self._conexiones:
                self._conexiones.remove(c)
        try:
            c.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            c.sock.close()
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════════════
# Guion del replay y línea de órdenes
# ══════════════════════════════════════════════════════════════════════
class ProgramaGuion:
    """Guion del replay (injerto A §8.24): {"spread": {…}, "halts": […], "rechazos": […], "fills_parciales": […]}.

    Mismo formato que lee `fuente_senales.Guion` (toda clave opcional); aquí
    se valida más estricto (una clave de primer nivel desconocida es un
    error: el guion es de un test). `aplicar_inicio` programa rechazos y
    parciales en el libro; `aplicar_hasta` aplica los halts y reaperturas
    cuya hora ET ya pasó (cada uno una sola vez).
    """

    CLAVES = ("spread", "halts", "rechazos", "fills_parciales")

    def __init__(self, datos: dict) -> None:
        if not isinstance(datos, dict):
            raise ValueError(f"el guion debe ser un objeto JSON: {datos!r}")
        sobrantes = set(datos) - set(self.CLAVES)
        if sobrantes:
            raise ValueError(f"claves desconocidas en el guion: {sorted(sobrantes)}")
        spread = datos.get("spread")
        spread = {} if spread is None else spread
        if not isinstance(spread, dict):
            raise ValueError(f"guion.spread debe ser un objeto: {spread!r}")
        base = ModeloSpread()
        self.spread = ModeloSpread(
            pct=de_float(spread["pct"]) if "pct" in spread else base.pct,
            minimo_ticks=spread.get("minimo_ticks", base.minimo_ticks),
            tamano_bid=spread.get("tamano_bid", base.tamano_bid),
            tamano_ask=spread.get("tamano_ask", base.tamano_ask),
        )
        self.halts = [self._halt(h) for h in _lista(datos, "halts")]
        self.rechazos = [self._rechazo(r) for r in _lista(datos, "rechazos")]
        self.fills_parciales = [self._parcial(f) for f in _lista(datos, "fills_parciales")]
        self._halts_aplicados: set[int] = set()
        self._reaperturas_aplicadas: set[int] = set()

    @classmethod
    def cargar(cls, ruta: Path | str) -> "ProgramaGuion":
        """Lee el JSON (UTF-8). Lanza si no existe o no es válido."""
        with Path(ruta).open("r", encoding="utf-8") as f:
            return cls(json.load(f))

    @staticmethod
    def _halt(h: dict) -> dict[str, Any]:
        ticker = _palabra("halts.ticker", h.get("ticker"))
        desde = _hora_guion("halts.desde", h.get("desde"))
        hasta = _hora_guion("halts.hasta", h["hasta"]) if h.get("hasta") is not None else None
        ta = h.get("ta", "H")
        if ta not in _TA_PARADO:
            raise ValueError(f"halts.ta debe ser H, P o Q: {ta!r}")
        tat = h.get("tat") or desde.strftime("%H:%M:%S")
        precio = h.get("precio_reapertura")
        if hasta is not None and (hasta <= desde or precio is None):
            raise ValueError(f"halt de {ticker}: 'hasta' debe ser posterior a 'desde' y llevar precio_reapertura")
        return {"ticker": ticker, "desde": desde, "hasta": hasta, "ta": ta, "tat": _palabra("halts.tat", tat),
                "precio_reapertura": _precio_positivo("halts.precio_reapertura", precio) if precio is not None else None}

    @staticmethod
    def _rechazo(r: dict) -> dict[str, Any]:
        accion = r.get("accion", "Send_Rej")
        if accion not in ACCIONES_RECHAZO:
            raise ValueError(f"rechazos.accion desconocida: {accion!r}")
        notas = r.get("notas")
        if not isinstance(notas, str) or not notas.strip():
            raise ValueError(f"rechazos.notas debe ser texto no vacío: {notas!r}")
        objetivo = r.get("token_o_orden")
        if objetivo is not None and type(objetivo) is not int:
            raise ValueError(f"rechazos.token_o_orden debe ser entero o null: {objetivo!r}")
        return {"notas": notas, "accion": accion, "token_o_orden": objetivo}

    @staticmethod
    def _parcial(f: dict) -> dict[str, Any]:
        ticker = f.get("ticker")
        if ticker is not None:
            ticker = _palabra("fills_parciales.ticker", ticker)
        fraccion = de_float(f.get("fraccion"))
        if not (0 < fraccion <= 1):
            raise ValueError(f"fills_parciales.fraccion fuera de (0, 1]: {fraccion}")
        return {"ticker": ticker, "fraccion": fraccion}

    def aplicar_inicio(self, libro: LibroSimulado) -> None:
        """Rechazos y fills parciales del guion al libro (antes de que llegue ninguna orden)."""
        for r in self.rechazos:
            libro.rechazar_siguiente(r["notas"], r["accion"], token_o_orden=r["token_o_orden"])
        for f in self.fills_parciales:
            libro.llenar_parcial(f["fraccion"], ticker=f["ticker"])

    def aplicar_hasta(self, simulador: SimuladorDAS, ahora_et: datetime) -> list[str]:
        """Aplica los halts con `desde ≤ ahora` y las reaperturas con `hasta ≤ ahora` no aplicados aún; devuelve qué hizo."""
        hecho: list[str] = []
        ahora = ahora_et.time().replace(microsecond=0)
        for i, h in enumerate(self.halts):
            if i not in self._halts_aplicados and ahora >= h["desde"]:
                simulador.libro.halt(h["ticker"], h["ta"], h["tat"])
                self._halts_aplicados.add(i)
                hecho.append(f"halt {h['ticker']} TA:{h['ta']}")
            if (h["hasta"] is not None and i in self._halts_aplicados and i not in self._reaperturas_aplicadas
                    and ahora >= h["hasta"]):
                simulador.reabrir(h["ticker"], h["precio_reapertura"], tat=h["hasta"].strftime("%H:%M:%S"))
                self._reaperturas_aplicadas.add(i)
                hecho.append(f"reabrir {h['ticker']} a {_num(h['precio_reapertura'])}")
        return hecho


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m app.bot_das.simulador_das --puerto 9800 --guion f.json` (§3.3): DAS falso para probar a mano.

    `--usuario/--clave` (inventados) restringen el LOGIN; sin ellos se acepta
    cualquiera. `--segundos S` para al cabo de S segundos (tests); sin él,
    hasta Ctrl+C. Cada 0,2 s aplica el guion con la hora ET real y hace `tic()`.
    """
    parser = argparse.ArgumentParser(prog="python -m app.bot_das.simulador_das",
                                     description="DAS falso: servidor TCP del CMD API para pruebas.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--puerto", type=int, default=9800)
    parser.add_argument("--guion", type=Path, default=None)
    parser.add_argument("--usuario", default=None)
    parser.add_argument("--clave", default=None)
    parser.add_argument("--segundos", type=float, default=None)
    parser.add_argument("--replace-share-total", action="store_true",
                        help="A-02: el share de REPLACE es la cantidad TOTAL (llenas + abierta), no la abierta")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if (args.usuario is None) != (args.clave is None):
        parser.error("--usuario y --clave van juntos")
    libro = LibroSimulado()
    reloj = Reloj()
    programa = ProgramaGuion.cargar(args.guion) if args.guion is not None else None
    if programa is not None:
        programa.aplicar_inicio(libro)
    usuarios = {args.usuario: args.clave} if args.usuario is not None else None
    emparejador = Emparejador(libro, reloj, replace_share_es_abierta=not args.replace_share_total)
    simulador = SimuladorDAS(libro, reloj, host=args.host, puerto=args.puerto, usuarios=usuarios,
                             emparejador=emparejador)
    host, puerto = simulador.arrancar()
    print(f"simulador DAS escuchando en {host}:{puerto}", flush=True)
    limite = time.monotonic() + args.segundos if args.segundos is not None else None
    try:
        while limite is None or time.monotonic() < limite:
            espera = 0.2 if limite is None else max(0.0, min(0.2, limite - time.monotonic()))
            time.sleep(espera)
            if programa is not None:
                for hecho in programa.aplicar_hasta(simulador, reloj.ahora()):
                    print(f"guion: {hecho}", flush=True)
            simulador.tic()
    except KeyboardInterrupt:
        pass
    finally:
        simulador.parar()
    return 0


# ══════════════════════════════════════════════════════════════════════
# ayudantes privados
# ══════════════════════════════════════════════════════════════════════
def _num(valor: Optional[Decimal], decimales: Optional[int] = None) -> str:
    """Decimal → texto sin notación científica ni ceros de más ("10.3", "100", "0.0123"); con `decimales`, redondeado."""
    if valor is None:
        return "0"
    if decimales is not None:
        valor = valor.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    texto = format(valor.normalize(), "f")
    return "0" if texto in ("-0", "0") else texto


def _es_evento(linea: str) -> bool:
    return linea.split(" ", 1)[0].upper() in _EVENTOS


def _stop_coherente(lado: str, stop: Optional[Decimal], precio: Optional[Decimal]) -> bool:
    """STOPLMTP de compra: límite ≥ disparo; de venta/corto: límite ≤ disparo (como exige `OrdenNueva`)."""
    if stop is None or precio is None:
        return False
    return precio >= stop if lado == "B" else precio <= stop


def _int(texto: str) -> int:
    if not _RE_ENTERO.fullmatch(texto):
        raise _ComandoMalo(f"entero esperado: {texto!r}")
    return int(texto)


def _int32(texto: str) -> int:
    valor = _int(texto)
    if not (_MIN_INT32 <= valor <= _MAX_INT32):
        raise _ComandoMalo(f"token fuera de int32: {texto!r}")
    return valor


def _dec(texto: str) -> Decimal:
    try:
        valor = Decimal(texto)
    except (InvalidOperation, ValueError) as exc:
        raise _ComandoMalo(f"número esperado: {texto!r}") from exc
    if not valor.is_finite():
        raise _ComandoMalo(f"número no finito: {texto!r}")
    return valor


def _palabra(nombre: str, valor: Any) -> str:
    """Campo de protocolo: texto no vacío y sin espacios (un espacio desplazaría los campos de la línea)."""
    if not isinstance(valor, str) or not valor or any(ch.isspace() for ch in valor):
        raise ValueError(f"{nombre} inválido: {valor!r}")
    return valor


def _precio_positivo(nombre: str, valor: Any) -> Decimal:
    d = de_float(valor)
    if d <= 0:
        raise ValueError(f"{nombre} debe ser > 0: {valor!r}")
    return d


def _precio_no_negativo(nombre: str, valor: Any) -> Decimal:
    d = de_float(valor)
    if d < 0:
        raise ValueError(f"{nombre} debe ser ≥ 0: {valor!r}")
    return d


def _hora_guion(nombre: str, valor: Any) -> dtime:
    if not isinstance(valor, str):
        raise ValueError(f"{nombre} debe ser 'HH:MM[:SS]': {valor!r}")
    m = _RE_HORA.fullmatch(valor.strip())
    if m is None:
        raise ValueError(f"{nombre} debe ser 'HH:MM[:SS]': {valor!r}")
    return dtime(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def _lista(datos: dict, nombre: str) -> list[dict]:
    valor = datos.get(nombre, [])
    if not isinstance(valor, list) or not all(isinstance(x, dict) for x in valor):
        raise ValueError(f"guion.{nombre} debe ser una lista de objetos: {valor!r}")
    return valor


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
