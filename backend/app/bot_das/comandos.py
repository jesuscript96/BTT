"""Comandos del grupo B de Telegram y botones del cuadro de mandos.

QUÉ HACE. `parsear` convierte un texto de Telegram en un `Comando` (o en
`None` si el chat no está autorizado o el texto no es un comando), con la
clase de confirmación que exige R-M-04: los de CONSULTA van sin confirmar,
los de acción sobre el bot en DOS PASOS (`Confirmaciones`: «Confirma con
/confirmar 1234», caducidad y un solo uso) y los de acción sobre el mercado
con «SI» explícito al final. `responder_consulta` compone, sin I/O, la
respuesta de cada comando de consulta sobre `EstadoBot`/`Config` y el
mercado de DAS. `ReceptorTelegram` hace long polling de `getUpdates` por
`urllib` en un `HiloVigilado` y entrega cada `Comando` por `al_comando`;
`LectorComandosFichero` lee los botones del cuadro de `estado/comandos.jsonl`
(idempotente por `id`).

POR QUÉ ESTÁ AQUÍ. R-Q-01: solo los dos chat_id autorizados (Jaume y socio)
pueden hablar con el bot, y lo que cambia algo pide confirmación. R-M-04 fija
la lista de comandos y lo que contesta cada uno. El decisor es el único que
muta `EstadoBot`: aquí solo se traduce texto a `Comando` y se contesta a las
consultas; ejecutar un comando es cosa del decisor (`ComandoRecibido`).

LAS TRAMPAS.
  * El chat se filtra ANTES de parsear (en el receptor) y otra vez en
    `parsear`: un bot de Telegram contesta a cualquiera que le escriba. Un
    chat no autorizado no deja el texto en el log (podría traer un secreto
    o datos personales): solo su chat_id y la longitud.
  * `autorizados` vacío = NADIE autorizado, nunca «todos».
  * En grupos Telegram añade «@NombreDelBot» al comando (`/estado@MiBot`):
    se quita antes de mirar el nombre.
  * Un «/cerrar SI» sin ticker, un «/stop X 1,234» fuera del tick o un
    «/log 100000» se devuelven como `requiere="args_invalidos"` con su uso:
    nunca llega al decisor una acción de mercado a medio escribir.
  * «SI» es la ÚLTIMA palabra y se quita de `args`; si falta, el comando
    vuelve con `requiere="si_faltante"` para que el decisor conteste cómo se
    escribe (R-M-04), NUNCA se ejecuta.
  * La confirmación en dos pasos exige el MISMO chat_id que la pidió, caduca
    (reloj monotónico inyectado) y se consume al usarla: un «/confirmar»
    repetido o reenviado no ejecuta dos veces.
  * Comandos viejos: Telegram guarda los mensajes no confirmados 24 h y el
    fichero del cuadro crece todo el día; al reiniciar el bot, un
    «/cerrar_todo SI» de hace una hora NO se ejecuta. Se descarta todo
    comando más viejo que `caducidad_s` (fecha del mensaje de Telegram o
    campo `t` del fichero, contra `reloj.epoch()`).
  * La URL de la API lleva el token: jamás se escribe en el log; los
    errores de `urllib` se registran pasados por `_sin_token`.
  * `responder_consulta` es PURA: el texto va con `parse_mode=HTML` en
    `CanalTelegram`, así que TODO valor dinámico (nombres de estrategia,
    notas de DAS, líneas del log) se escapa con `html.escape`; si no, un «<»
    en un nombre hace que Telegram rechace el mensaje entero con 400.
  * El fichero de comandos se lee por offset de bytes y solo hasta el último
    salto de línea: una línea a medio escribir por el cuadro se deja para la
    vuelta siguiente, no se descarta como JSON roto.
  * Idempotencia del fichero: se persiste `ultimo_id`/`offset` ANTES de
    entregar el comando (como mucho una vez: preferible perder un botón a
    cerrar dos veces una posición). Telegram, igual (C-02): el receptor
    persiste su offset en `estado/telegram_offset` antes de entregar y lo
    confirma a Telegram al parar; un reinicio no repite un «/cerrar X N SI».
  * «/sigue TICKER» y «/parar_avisos TICKER [BS]» / «/reanudar_avisos
    TICKER [BS]» llevan el ticker en `args` (C-01, G1A-08, G1A-19); el
    decisor es quien levanta el veto de reentrada o calla solo ese cisne.
"""
from __future__ import annotations

import html
import json
import logging
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from app.bot_das.cerrojo import HiloVigilado
from app.bot_das.tipos import (
    Comando,
    Config,
    EstadoBot,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    Fill,
    Lote,
    Orden,
    PosicionTicker,
    Proposito,
    en_tick,
)

logger = logging.getLogger("btt.bot_das.comandos")

# ── conjuntos de comandos (§3.10, R-M-04) ──────────────────────────────
CONSULTA = frozenset({"estado", "posiciones", "ordenes", "locates", "estrategias", "detalle", "salud", "log"})
DOS_PASOS = frozenset({"pausar", "reanudar", "sigue", "modo_seguridad", "desactivar", "activar", "apagar", "encender",
                       "reanudar_ticker", "reanudar_todo", "parar_avisos", "reanudar_avisos", "control_humano",
                       "cerrar_y_reiniciar", "esperar_fin_dia"})
CON_SI = frozenset({"cerrar_todo", "cerrar", "cancelar_ordenes", "stop"})
CONFIRMAR = "confirmar"

# ── valores de `Comando.requiere` ───────────────────────────────────────
REQUIERE_NADA = "nada"                    # consulta: se contesta ya
REQUIERE_CONFIRMACION = "confirmacion"    # dos pasos: el decisor llama a Confirmaciones.pedir
REQUIERE_SI = "si"                        # acción de mercado con «SI»: se ejecuta ya
REQUIERE_SI_FALTANTE = "si_faltante"      # acción de mercado sin «SI»: se contesta cómo se escribe, NO se ejecuta
REQUIERE_CONFIRMADO = "confirmado"        # dos pasos ya confirmado (o botón del cuadro): se ejecuta ya
REQUIERE_CONFIRMAR = "confirmar"          # «/confirmar 1234»: el decisor lo pasa a Confirmaciones.confirmar
REQUIERE_ARGS_INVALIDOS = "args_invalidos"
REQUIERE_DESCONOCIDO = "desconocido"
EJECUTABLES = frozenset({REQUIERE_NADA, REQUIERE_SI, REQUIERE_CONFIRMADO})

# ── uso de cada comando (lo que se contesta con args_invalidos) ─────────
USO: dict[str, str] = {
    "estado": "/estado",
    "posiciones": "/posiciones",
    "ordenes": "/ordenes",
    "locates": "/locates",
    "estrategias": "/estrategias",
    "detalle": "/detalle ID (token, id de DAS, lote, ticker o estrategia)",
    "salud": "/salud",
    "log": "/log [N] (1-50, por defecto 20)",
    "pausar": "/pausar",
    "reanudar": "/reanudar [TICKER]",
    "sigue": "/sigue [TICKER] (con TICKER: levanta el veto de reentrada tras un cisne negro)",
    "modo_seguridad": "/modo_seguridad on|off",
    "desactivar": "/desactivar ESTRATEGIA",
    "activar": "/activar ESTRATEGIA",
    "apagar": "/apagar",
    "encender": "/encender",
    "reanudar_ticker": "/reanudar_ticker TICKER",
    "reanudar_todo": "/reanudar_todo",
    "parar_avisos": "/parar_avisos [TICKER [BS]]",
    "reanudar_avisos": "/reanudar_avisos [TICKER [BS]]",
    "control_humano": "/control_humano [TICKER]",
    "cerrar_y_reiniciar": "/cerrar_y_reiniciar ESTRATEGIA",
    "esperar_fin_dia": "/esperar_fin_dia ESTRATEGIA",
    "cerrar_todo": "/cerrar_todo SI",
    "cerrar": "/cerrar TICKER [ACCIONES] SI",
    "cancelar_ordenes": "/cancelar_ordenes TICKER SI",
    "stop": "/stop TICKER PRECIO SI",
    "confirmar": "/confirmar ID",
}

API_TELEGRAM = "https://api.telegram.org"
ESPERA_POLLING_S = 25                     # §3.10: long polling de 25 s
CADUCIDAD_COMANDO_S = 120.0               # un comando más viejo que esto no se ejecuta (reinicio con cola vieja)
TTL_CONFIRMACION_S = 60.0                 # §3.10
LECTURA_FICHERO_S = 1.0                   # §3.10: el fichero del cuadro se lee cada 1 s
ESPERA_ERROR_RED_S = 5.0                  # tras un fallo de getUpdates, antes de volver a preguntar
RONDA_MIN_S = 0.5                         # getUpdates que vuelve antes de esto (sin long polling) → pausa antes del siguiente
LOG_LINEAS_DEFECTO = 20
LOG_LINEAS_MAX = 50
FILAS_MAX = 40                            # filas por respuesta (Telegram corta a 4.096 unidades)
ARG_MAX_CARACTERES = 80
CHAT_ID_CUADRO = 0                        # los botones del cuadro no tienen chat
MASCARA = "*****"
FICHERO_OFFSET_TELEGRAM = "telegram_offset"   # C-02: estado/telegram_offset (el ejecutor pasa dir_estado / esto)

_PATRON_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_PATRON_TOKEN_URL = re.compile(r"bot\d+:[A-Za-z0-9_-]+")
_PALABRAS_SI = frozenset({"SI", "SÍ"})
_ESTADOS_TERMINALES = frozenset({EstadoOrden.CANCELED, EstadoOrden.REJECTED, EstadoOrden.EXECUTED, EstadoOrden.CLOSED})
_LOTES_VIVOS = frozenset({EstadoLote.ABRIENDO, EstadoLote.ABIERTO, EstadoLote.CERRANDO})
_PROPOSITOS_STOP = frozenset({Proposito.STOP_PRINCIPAL, Proposito.STOP_EMERGENCIA, Proposito.STOP_PROTECCION})
_PROPOSITOS_TP = frozenset({Proposito.TP_AGREGAR, Proposito.TP_CRUCE})


# ═══════════════════════════ parseo ════════════════════════════════════
def parsear(texto: str, chat_id: int, autorizados: frozenset[int], id_comando: str = "") -> Optional[Comando]:
    """Texto de Telegram → `Comando` (R-M-04, R-Q-01; §3.10).

    None si `chat_id` no está en `autorizados` (se registra el intento SIN el
    texto) o si el texto no empieza por «/» (texto libre: gancho de R-M-06,
    el asistente de IA irá ahí después del canario). Nombre en minúsculas y
    sin la barra ni el sufijo «@bot»; args separados por espacios.
    `requiere`: CONSULTA → "nada"; DOS_PASOS → "confirmacion"; CON_SI →
    "si" si la última palabra es SI (se quita de args) o "si_faltante";
    "/confirmar" → "confirmar"; nombre desconocido → "desconocido"; args
    que no cuadran con `USO` → "args_invalidos" (trampa: nunca llega al
    decisor un «/cerrar SI» sin ticker). Los tickers salen en mayúsculas.
    """
    if not isinstance(texto, str):
        return None
    if type(chat_id) is not int or chat_id not in autorizados:
        logger.warning("[COMANDOS] chat_id %s no autorizado: mensaje de %d caracteres ignorado",
                       chat_id, len(texto))
        return None
    limpio = texto.strip()
    if not limpio.startswith("/"):
        return None
    partes = limpio.split()
    nombre = partes[0][1:].split("@", 1)[0].lower()
    args = partes[1:]
    return _construir(nombre, args, chat_id, id_comando, limpio, desde_cuadro=False)


def _construir(nombre: str, args: list[str], chat_id: int, id_comando: str, texto: str,
               desde_cuadro: bool) -> Comando:
    """Clasifica y valida; común a Telegram y al fichero del cuadro."""
    if nombre == CONFIRMAR and not desde_cuadro:
        ok = len(args) == 1 and args[0].isdigit() and len(args[0]) == 4
        return Comando(nombre=nombre, args=list(args), chat_id=chat_id,
                       requiere=REQUIERE_CONFIRMAR if ok else REQUIERE_ARGS_INVALIDOS, id=id_comando, texto=texto)
    if nombre not in CONSULTA and nombre not in DOS_PASOS and nombre not in CON_SI:
        return Comando(nombre=nombre, args=list(args), chat_id=chat_id, requiere=REQUIERE_DESCONOCIDO,
                       id=id_comando, texto=texto)
    con_si = False
    if nombre in CON_SI and args and args[-1].upper() in _PALABRAS_SI:
        con_si = True
        args = args[:-1]
    normalizados = _validar_args(nombre, args)
    if normalizados is None:
        return Comando(nombre=nombre, args=list(args), chat_id=chat_id, requiere=REQUIERE_ARGS_INVALIDOS,
                       id=id_comando, texto=texto)
    if nombre in CONSULTA:
        requiere = REQUIERE_NADA
    elif desde_cuadro:
        requiere = REQUIERE_CONFIRMADO     # el botón del cuadro ES la confirmación (fichero local, R-M-03)
    elif nombre in DOS_PASOS:
        requiere = REQUIERE_CONFIRMACION
    else:
        requiere = REQUIERE_SI if con_si else REQUIERE_SI_FALTANTE
    return Comando(nombre=nombre, args=normalizados, chat_id=chat_id, requiere=requiere, id=id_comando, texto=texto)


def _ticker(arg: str) -> Optional[str]:
    t = arg.upper()
    return t if _PATRON_TICKER.match(t) else None


def _entero(arg: str, minimo: int, maximo: int) -> Optional[str]:
    if not arg.isdigit():
        return None
    n = int(arg)
    return str(n) if minimo <= n <= maximo else None


def _precio(arg: str) -> Optional[str]:
    """Precio de «/stop»: coma decimal admitida (móvil en castellano), finito, > 0 y AL TICK (injerto A §8.1)."""
    texto = arg.replace(",", ".") if "." not in arg else arg
    try:
        p = Decimal(texto)
    except (InvalidOperation, ValueError):
        return None
    if not p.is_finite() or p <= 0 or not en_tick(p):
        return None
    return str(p)


def _libre(arg: str) -> Optional[str]:
    return arg if 0 < len(arg) <= ARG_MAX_CARACTERES else None


def _validar_args(nombre: str, args: list[str]) -> Optional[list[str]]:
    """Args normalizados según `USO`, o None si no cuadran (número o forma)."""
    n = len(args)
    if nombre in ("estado", "posiciones", "ordenes", "locates", "estrategias", "salud", "pausar",
                  "apagar", "encender", "reanudar_todo", "cerrar_todo"):
        return [] if n == 0 else None
    if nombre == "sigue":
        # C-01 / DC-03 / G1A-08 (R-G-03): «/sigue TICKER» levanta el veto de reentrada tras un cisne negro;
        # «/sigue» a secas solo la pausa global. El decisor aplica el ticker (args = [TICKER]).
        if n == 0:
            return []
        v = _ticker(args[0]) if n == 1 else None
        return [v] if v is not None else None
    if nombre in ("parar_avisos", "reanudar_avisos"):
        # C-01 / G1A-19 (R-G-01, §5 F7): «/parar_avisos X BS» calla SOLO los informes del cisne negro de X.
        # «BS» es opcional y se normaliza fuera: args = [TICKER]. Sin args: lo que decida el decisor.
        if n == 0:
            return []
        if n > 2 or (n == 2 and args[1].upper() != "BS"):
            return None
        v = _ticker(args[0])
        return [v] if v is not None else None
    if nombre == "log":
        if n == 0:
            return []
        v = _entero(args[0], 1, LOG_LINEAS_MAX) if n == 1 else None
        return [v] if v is not None else None
    if nombre in ("detalle", "desactivar", "activar", "cerrar_y_reiniciar", "esperar_fin_dia"):
        v = _libre(args[0]) if n == 1 else None
        return [v] if v is not None else None
    if nombre == "modo_seguridad":
        v = args[0].lower() if n == 1 else None
        return [v] if v in ("on", "off") else None
    if nombre in ("reanudar", "control_humano"):
        if n == 0:
            return []
        v = _ticker(args[0]) if n == 1 else None
        return [v] if v is not None else None
    if nombre in ("reanudar_ticker", "cancelar_ordenes"):
        v = _ticker(args[0]) if n == 1 else None
        return [v] if v is not None else None
    if nombre == "cerrar":
        if n not in (1, 2):
            return None
        t = _ticker(args[0])
        if t is None:
            return None
        if n == 1:
            return [t]
        q = _entero(args[1], 1, 10_000_000)
        return [t, q] if q is not None else None
    if nombre == "stop":
        if n != 2:
            return None
        t, p = _ticker(args[0]), _precio(args[1])
        return [t, p] if t is not None and p is not None else None
    return None


def respuesta_previa(c: Comando) -> Optional[str]:
    """Lo que se contesta a un comando que NO se ejecuta (R-M-04: «SI» explícito; uso de cada comando).

    None si el comando es ejecutable o espera confirmación (eso lo contesta
    `Confirmaciones.pedir`). Texto plano escapado para `parse_mode=HTML`.
    """
    if c.requiere == REQUIERE_SI_FALTANTE:
        return _esc(f"Falta «SI»: no hago nada. Escribe {_ejemplo_con_si(c)}")
    if c.requiere == REQUIERE_ARGS_INVALIDOS:
        return _esc(f"No entiendo los argumentos. Uso: {USO.get(c.nombre, '/' + c.nombre)}")
    if c.requiere == REQUIERE_DESCONOCIDO:
        nombres = " ".join("/" + n for n in sorted(CONSULTA | DOS_PASOS | CON_SI))
        return _esc(f"Comando desconocido «/{c.nombre[:ARG_MAX_CARACTERES]}». Comandos: {nombres}")
    return None


def _ejemplo_con_si(c: Comando) -> str:
    return " ".join(["/" + c.nombre, *c.args, "SI"])


# ═══════════════════════════ dos pasos ═════════════════════════════════
class Confirmaciones:
    """Confirmación en dos pasos con caducidad y un solo uso (R-M-04, R-Q-01; §3.10).

    `pedir` guarda el comando bajo un id de 4 cifras (random.SystemRandom:
    no predecible) y devuelve el texto a mandar; `confirmar` lo devuelve con
    `requiere="confirmado"` si el id existe, no ha caducado (reloj.mono()
    inyectado) y lo confirma el MISMO chat_id que lo pidió. Trampas: un id
    confirmado se borra (un reenvío no ejecuta dos veces); un chat distinto
    no lo consume (el dueño aún puede confirmar); los caducados se purgan.
    """

    def __init__(self, reloj, ttl_s: float = TTL_CONFIRMACION_S) -> None:
        if ttl_s <= 0:
            raise ValueError(f"ttl_s debe ser > 0: {ttl_s}")
        self._reloj = reloj
        self._ttl_s = float(ttl_s)
        self._pendientes: dict[str, tuple[Comando, float]] = {}
        self._azar = random.SystemRandom()

    @property
    def pendientes(self) -> int:
        self._purgar()
        return len(self._pendientes)

    def pedir(self, c: Comando) -> str:
        """Guarda `c` y devuelve «/nombre args» + «Confirma con /confirmar <id> …»."""
        self._purgar()
        if len(self._pendientes) >= 9000:
            raise RuntimeError("demasiadas confirmaciones pendientes")
        while True:
            ident = str(self._azar.randint(1000, 9999))
            if ident not in self._pendientes:
                break
        self._pendientes[ident] = (c, self._reloj.mono() + self._ttl_s)
        orden = " ".join(["/" + c.nombre, *c.args])
        return _esc(f"{orden}\nConfirma con /confirmar {ident} (caduca en {int(self._ttl_s)} s)")

    def confirmar(self, chat_id: int, texto: str) -> Optional[Comando]:
        """«/confirmar 1234» (o «1234») del mismo chat → el comando pedido, UNA vez; si no, None."""
        ident = _id_confirmacion(texto)
        if ident is None:
            return None
        self._purgar()
        guardado = self._pendientes.get(ident)
        if guardado is None:
            logger.info("[COMANDOS] confirmación %s inexistente o caducada", ident)
            return None
        comando, _ = guardado
        if comando.chat_id != chat_id:
            logger.warning("[COMANDOS] confirmación %s desde otro chat (%s); se ignora", ident, chat_id)
            return None
        del self._pendientes[ident]
        return replace(comando, requiere=REQUIERE_CONFIRMADO)

    def _purgar(self) -> None:
        ahora = self._reloj.mono()
        for ident in [k for k, (_, vence) in self._pendientes.items() if ahora >= vence]:
            del self._pendientes[ident]


def _id_confirmacion(texto: str) -> Optional[str]:
    if not isinstance(texto, str):
        return None
    partes = texto.strip().split()
    if len(partes) == 2 and partes[0].split("@", 1)[0].lower() == "/" + CONFIRMAR:
        cand = partes[1]
    elif len(partes) == 1:
        cand = partes[0]
    else:
        return None
    return cand if len(cand) == 4 and cand.isdigit() else None


# ═══════════════════════════ consultas (PURO) ══════════════════════════
def responder_consulta(c: Comando, estado: EstadoBot, cfg: Config, mercado: Any, ahora: float,
                       lineas_log: Optional[Sequence[str]] = None) -> str:
    """Respuesta de un comando de CONSULTA (R-M-04, R-M-01 «detalle»; §3.10). PURA: sin I/O ni reloj.

    `mercado` solo se usa por `cotizacion(ticker)` y `foto()` (MercadoDAS,
    lote E1; puede ser None). `ahora` es monotónico, como los `*_en` del
    estado. `lineas_log` son las últimas líneas del log/diario que el
    llamante ya leyó (esta función no toca disco). Todo valor dinámico va
    escapado para `parse_mode=HTML`. ValueError si `c` no es de consulta.
    """
    if c.nombre not in CONSULTA:
        raise ValueError(f"no es un comando de consulta: {c.nombre!r}")
    if c.nombre == "estado":
        return _resp_estado(estado, cfg, mercado, ahora)
    if c.nombre == "posiciones":
        return _resp_posiciones(estado, mercado)
    if c.nombre == "ordenes":
        return _resp_ordenes(estado, ahora)
    if c.nombre == "locates":
        return _resp_locates(estado, cfg)
    if c.nombre == "estrategias":
        return _resp_estrategias(estado, cfg)
    if c.nombre == "detalle":
        return _resp_detalle(c.args[0] if c.args else "", estado, cfg, mercado)
    if c.nombre == "salud":
        return _resp_salud(estado, mercado, ahora)
    n = int(c.args[0]) if c.args else LOG_LINEAS_DEFECTO
    return _resp_log(n, lineas_log)


def _esc(valor: Any) -> str:
    return html.escape(str(valor), quote=False)


def _titulo(texto: str) -> str:
    return f"<b>{_esc(texto)}</b>"


def _usd(valor: Optional[Decimal]) -> str:
    if valor is None:
        return "?"
    return f"{valor.quantize(Decimal('0.01')):,} $".replace(",", " ")


def _precio_txt(valor: Optional[Decimal]) -> str:
    return "—" if valor is None else str(valor)


def _edad(desde: Optional[float], ahora: float) -> str:
    if desde is None:
        return "nunca"
    return f"hace {max(0.0, ahora - desde):.1f} s"


def _limitar(filas: list[str]) -> list[str]:
    if len(filas) <= FILAS_MAX:
        return filas
    return filas[:FILAS_MAX] + [f"… y {len(filas) - FILAS_MAX} más"]


def _cotizacion(mercado: Any, ticker: str) -> Any:
    if mercado is None:
        return None
    try:
        return mercado.cotizacion(ticker)
    except Exception as exc:  # noqa: BLE001 — frontera: el mercado es de otro lote; una consulta no tumba al decisor (H-5)
        logger.warning("[COMANDOS] cotización de %s no disponible: %s", ticker, exc)
        return None


def _es_largo(lote: Lote) -> bool:
    """Todas las estrategias de hoy son cortas; «Long…» en `direccion` es el único caso largo (como reglas.salidas)."""
    return str(lote.direccion).strip().lower().startswith("long")


def _marca(cot: Any, largo: bool) -> Optional[Decimal]:
    """Precio al que se cerraría: corto → ask; largo → bid; si falta, last."""
    if cot is None:
        return None
    lado = getattr(cot, "bid" if largo else "ask", None)
    return lado if lado is not None else getattr(cot, "last", None)


def _fills_del_ticker(estado: EstadoBot, ticker: str) -> list[Fill]:
    return [f for lista in estado.fills.values() for f in lista if f.ticker == ticker]


def _pnl_dia_ticker(estado: EstadoBot, pos: PosicionTicker, mercado: Any) -> Optional[Decimal]:
    """PnL del día por caja: Σ ventas − Σ compras + neta × marca (sin comisiones).

    Trampa: supone la posición plana al empezar el día (el libro de fills es
    del día); si la neta no es 0 y no hay cotización, None (no se inventa).
    """
    caja = Decimal("0")
    for f in _fills_del_ticker(estado, pos.ticker):
        importe = f.precio * f.qty
        caja += -importe if f.lado == "B" else importe
    if pos.neta == 0:
        return caja
    marca = _marca(_cotizacion(mercado, pos.ticker), largo=pos.neta > 0)
    return None if marca is None else caja + marca * pos.neta


def _latente_lote(lote: Lote, cot: Any) -> Optional[Decimal]:
    if lote.llenas <= 0:
        return Decimal("0")
    largo = _es_largo(lote)
    marca = _marca(cot, largo)
    if marca is None:
        return None
    diferencia = (marca - lote.precio_medio) if largo else (lote.precio_medio - marca)
    return diferencia * lote.llenas


def _ordenes_vivas(estado: EstadoBot, ticker: Optional[str] = None) -> list[Orden]:
    vivas = [o for o in estado.ordenes.values() if o.estado not in _ESTADOS_TERMINALES]
    if ticker is not None:
        vivas = [o for o in vivas if o.ticker == ticker]
    return sorted(vivas, key=lambda o: (o.ticker, o.token))


def _resp_estado(estado: EstadoBot, cfg: Config, mercado: Any, ahora: float) -> str:
    """/estado: encendido o pausado, posiciones por estrategia, PnL del día, incidentes (R-M-04)."""
    if not estado.vigilando:
        marcha = "APAGADO"
    elif estado.control_humano:
        marcha = "CONTROL HUMANO"
    elif estado.pausa_global or cfg.pausar_entradas:
        marcha = "PAUSADO (sin entradas nuevas)"
    else:
        marcha = "EN MARCHA"
    filas = [_titulo(f"Estado · {estado.fase.value.upper()} · {estado.dia.isoformat()}"),
             _esc(f"Bot: {marcha}"),
             _esc(f"DAS: {'conectado' if estado.das_conectado else 'DESCONECTADO'}"
                  + (f" · degradado: {', '.join(sorted(estado.modo_degradado))}" if estado.modo_degradado else "")),
             _esc(f"Modo seguridad: {'ON' if cfg.modo_seguridad.get('activo') else 'off'}")]
    por_estrategia: dict[str, int] = {}
    for pos in estado.posiciones.values():
        for lote in pos.lotes.values():
            if lote.estado in _LOTES_VIVOS and lote.llenas > 0:
                por_estrategia[lote.estrategia] = por_estrategia.get(lote.estrategia, 0) + 1
    if por_estrategia:
        filas.append(_esc("Posiciones por estrategia: "
                          + ", ".join(f"{k} ×{v}" for k, v in sorted(por_estrategia.items()))))
    else:
        filas.append("Sin posiciones abiertas")
    total = Decimal("0")
    sin_precio: list[str] = []
    for ticker, pos in sorted(estado.posiciones.items()):
        pnl = _pnl_dia_ticker(estado, pos, mercado)
        if pnl is None:
            sin_precio.append(ticker)
        else:
            total += pnl
    linea_pnl = f"PnL del día (fills, sin comisiones): {_usd(total)}"
    if sin_precio:
        linea_pnl += f" · sin cotización: {', '.join(sin_precio)}"
    filas.append(_esc(linea_pnl))
    incidentes = [f"{t}: {p.estado.value}" + (f" ({p.motivo_estado})" if p.motivo_estado else "")
                  for t, p in sorted(estado.posiciones.items()) if p.estado is not EstadoTicker.NORMAL]
    if estado.ordenes_ajenas:
        incidentes.append(f"órdenes ajenas en DAS: {len(estado.ordenes_ajenas)}")
    if estado.locates_deshabilitados:
        incidentes.append("locates deshabilitados")
    filas.append(_esc("Incidentes: " + ("; ".join(incidentes) if incidentes else "ninguno")))
    filas.append(_esc(f"Última reconciliación: {_edad(estado.reconciliacion_ok_en, ahora)}"))
    return "\n".join(_limitar(filas))


def _resp_posiciones(estado: EstadoBot, mercado: Any) -> str:
    """/posiciones: cada lote con entrada, stop, take profit y PnL latente (R-M-04)."""
    filas = [_titulo("Posiciones")]
    for ticker, pos in sorted(estado.posiciones.items()):
        vivos = [l for l in pos.lotes.values() if l.estado in _LOTES_VIVOS]
        if pos.neta == 0 and not vivos:
            continue
        cot = _cotizacion(mercado, ticker)
        neta_das = "?" if pos.neta_das is None else str(pos.neta_das)
        filas.append(_esc(f"{ticker} · neta {pos.neta} (DAS {neta_das}) · {pos.estado.value}"
                          + (f" · bid {_precio_txt(cot.bid)} ask {_precio_txt(cot.ask)}" if cot is not None else "")))
        vivas = _ordenes_vivas(estado, ticker)
        stops = [o for o in vivas if o.proposito in _PROPOSITOS_STOP]
        tps = [o for o in vivas if o.proposito in _PROPOSITOS_TP]
        for lote in sorted(vivos, key=lambda l: l.id):
            latente = _latente_lote(lote, cot)
            stop_lote = [o for o in stops if o.lote_id in (None, lote.id)]
            tp_lote = [o for o in tps if o.lote_id == lote.id]
            texto_stop = ", ".join(f"{o.proposito.value} {_precio_txt(o.stop)}/{_precio_txt(o.precio)}"
                                   for o in stop_lote) or f"nivel {_precio_txt(lote.nivel_stop)} SIN ORDEN"
            texto_tp = ", ".join(f"{_precio_txt(o.precio)} ×{o.qty}" for o in tp_lote) or "—"
            filas.append(_esc(f"  {lote.estrategia} [{lote.estado.value}] {lote.llenas}/{lote.pedidas} a "
                              f"{lote.precio_medio} · stop {texto_stop} · TP {texto_tp} · "
                              f"latente {_usd(latente)}"))
    if len(filas) == 1:
        filas.append("Sin posiciones")
    return "\n".join(_limitar(filas))


def _resp_ordenes(estado: EstadoBot, ahora: float) -> str:
    """/ordenes: órdenes vivas en DAS, las nuestras y las ajenas (R-M-04, R-K-02)."""
    filas = [_titulo("Órdenes vivas")]
    for o in _ordenes_vivas(estado):
        precio = (f"{_precio_txt(o.stop)}→{_precio_txt(o.precio)}" if o.stop is not None
                  else _precio_txt(o.precio))
        filas.append(_esc(f"{o.ticker} {o.lado.value} {o.tipo.value} {o.llenas}/{o.qty} @ {precio} · "
                          f"{o.proposito.value} · {o.estado.value} · token {o.token}"
                          + (f" · id {o.id_das}" if o.id_das is not None else "")
                          + f" · {_edad(o.enviada_en or None, ahora)}"))
    for token, m in sorted(estado.ordenes_ajenas.items()):
        if m.estado in _ESTADOS_TERMINALES:
            continue
        filas.append(_esc(f"AJENA {m.ticker} {m.lado} {m.tipo} {m.qty} @ {m.precio} · {m.estado.value} · id {m.id}"))
    if len(filas) == 1:
        filas.append("Ninguna")
    return "\n".join(_limitar(filas))


def _resp_locates(estado: EstadoBot, cfg: Config) -> str:
    """/locates: comprados hoy, precio, usados o no y gasto frente al tope del 3 % (R-M-04, R-H-03)."""
    filas = [_titulo("Locates de hoy")]
    for (ticker, sid), loc in sorted(estado.locates.items()):
        filas.append(_esc(f"{ticker} · {sid} · {loc.localizadas}/{loc.pedidas} a {loc.precio_accion} $/acc · "
                          f"coste {_usd(loc.coste)} · usadas {loc.usadas} · {loc.estado}"))
    if len(filas) == 1:
        filas.append("Ninguno")
    pct = _decimal_o_none(cfg.locates.get("tope_gasto_pct_cuenta"))
    equity = estado.cuenta.equity
    if pct is not None and equity is not None:
        tope = equity * pct / 100
        filas.append(_esc(f"Gasto: {_usd(estado.gasto_locates_dia)} de {_usd(tope)} ({pct} % de {_usd(equity)})"))
    else:
        filas.append(_esc(f"Gasto: {_usd(estado.gasto_locates_dia)} (tope sin calcular: falta equity)"))
    if estado.locates_deshabilitados:
        filas.append("LOCATES DESHABILITADOS")
    return "\n".join(_limitar(filas))


def _decimal_o_none(valor: Any) -> Optional[Decimal]:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        d = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _ventanas(ventanas: list[dict]) -> str:
    partes = [f"{v.get('from_time', '?')}-{v.get('to_time', '?')}" for v in ventanas if isinstance(v, dict)]
    return ", ".join(partes) or "todo el día"


def _resp_estrategias(estado: EstadoBot, cfg: Config) -> str:
    """/estrategias: activas, ventana y tamaño (R-M-04)."""
    filas = [_titulo(f"Estrategias (config v{cfg.config_version})")]
    if cfg.pausar_entradas or estado.pausa_global:
        filas.append("Entradas PAUSADAS")
    for sid, e in sorted(cfg.estrategias.items()):
        marca = "OPERA" if e.ejecutar else "no opera"
        grupo_a = " · avisa A" if e.avisar_grupo_a else ""
        filas.append(_esc(f"{e.name} ({sid}) · {marca}{grupo_a} · ventana {_ventanas(e.ventana_entradas)}"
                          f" · fin {e.hora_fin_sesion or '—'} · riesgo {_usd(e.riesgo_usd)}"))
    if not cfg.estrategias:
        filas.append("Ninguna")
    return "\n".join(_limitar(filas))


def _resp_detalle(ident: str, estado: EstadoBot, cfg: Config, mercado: Any) -> str:
    """/detalle ID: orden (token o id de DAS), lote, ticker o estrategia (R-M-01 «detalle»)."""
    orden: Optional[Orden] = None
    if ident.lstrip("-").isdigit():
        n = int(ident)
        orden = estado.ordenes.get(n)
        if orden is None and n in estado.id_a_token:
            orden = estado.ordenes.get(estado.id_a_token[n])
    if orden is not None:
        o = orden
        return "\n".join([_titulo(f"Orden {o.token}"), _esc(
            f"{o.ticker} {o.lado.value} {o.tipo.value} qty {o.qty} llenas {o.llenas} canceladas {o.cxlqty} · "
            f"precio {_precio_txt(o.precio)} stop {_precio_txt(o.stop)} · ruta {o.ruta} · {o.proposito.value} · "
            f"lote {o.lote_id or '—'} · estado {o.estado.value} · id DAS {o.id_das if o.id_das is not None else '—'}"
            f" · intentos {o.intentos}" + (f" · notas: {o.notas}" if o.notas else ""))])
    for pos in estado.posiciones.values():
        lote = pos.lotes.get(ident)
        if lote is not None:
            return "\n".join([_titulo(f"Lote {lote.id}"), _esc(
                f"{lote.estrategia} ({lote.strategy_id}) · {lote.direccion} · {lote.estado.value} · "
                f"{lote.llenas}/{lote.pedidas} a {lote.precio_medio} · nivel stop {_precio_txt(lote.nivel_stop)} · "
                f"riesgo {_usd(lote.riesgo_usd)} · reentrada {lote.reentrada_n} · "
                f"salida {lote.hora_salida or '—'} · EOD {lote.eod or '—'}")])
    ticker = ident.upper()
    pos = estado.posiciones.get(ticker)
    if pos is not None:
        filas = [_titulo(f"Ticker {ticker}"), _esc(
            f"estado {pos.estado.value}" + (f" ({pos.motivo_estado})" if pos.motivo_estado else "")
            + f" · neta {pos.neta} · DAS {pos.neta_das if pos.neta_das is not None else '?'}"
            + f" · lotes {len(pos.lotes)} · órdenes vivas {len(_ordenes_vivas(estado, ticker))}"
            + (" · intervención humana" if pos.intervencion_humana else "")
            + (" · cisne negro" if pos.bs is not None else "")
            + (f" · entrada en curso ({pos.intento.fase.value})" if pos.intento is not None else ""))]
        pnl = _pnl_dia_ticker(estado, pos, mercado)
        filas.append(_esc(f"PnL del día: {_usd(pnl)}"))
        return "\n".join(filas)
    e = cfg.estrategias.get(ident)
    if e is not None:
        return "\n".join([_titulo(f"Estrategia {e.name}"), _esc(
            f"{e.strategy_id} · {'OPERA' if e.ejecutar else 'no opera'} · riesgo {_usd(e.riesgo_usd)} · "
            f"EV {e.ev_pct} % · ventana {_ventanas(e.ventana_entradas)} · fin {e.hora_fin_sesion or '—'} · "
            f"reentradas {'sí' if e.accept_reentries else 'no'} ({e.max_reentries}) · "
            f"al desactivar: {e.al_desactivar} · {e.definition_hash}")])
    return _esc(f"No encuentro «{ident}» (token, id de DAS, lote, ticker o estrategia)")


def _resp_salud(estado: EstadoBot, mercado: Any, ahora: float) -> str:
    """/salud: conexiones DAS y servidores, feed, reconciliación, mercado (R-M-04)."""
    filas = [_titulo("Salud"), _esc(f"DAS: {'conectado' if estado.das_conectado else 'DESCONECTADO'}")]
    for servidor, ok in sorted(estado.das_logon.items()):
        filas.append(_esc(f"  {servidor}: {'?' if ok is None else ('OK' if ok else 'CAÍDO')}"))
    filas.append(_esc(f"Feed (última vela): {_edad(estado.feed_ultima_vela_en, ahora)}"))
    filas.append(_esc(f"Reconciliación OK: {_edad(estado.reconciliacion_ok_en, ahora)}"))
    filas.append(_esc(f"Respuesta del último barrido: {_edad(estado.ultima_respuesta_barrido_en, ahora)}"))
    filas.append(_esc(f"Último fill: {_edad(estado.ultimo_fill_en, ahora)}"))
    filas.append(_esc("Modo degradado: " + (", ".join(sorted(estado.modo_degradado)) or "no")))
    filas.append(_esc(f"BP: {_usd(estado.cuenta.bp)} · leída {_edad(estado.cuenta.leida_en, ahora)}"))
    if mercado is not None:
        try:
            foto = mercado.foto()
        except Exception as exc:  # noqa: BLE001 — frontera: el mercado es de otro lote; /salud no tumba al decisor (H-5)
            filas.append(_esc(f"Mercado DAS: sin foto ({type(exc).__name__})"))
        else:
            halts = foto.get("halts") or {}
            filas.append(_esc(f"Mercado DAS: {foto.get('suscritos', '?')} suscritos de {foto.get('max_lv1', '?')}"
                              f" · halts {len(halts)}"))
    return "\n".join(_limitar(filas))


def _resp_log(n: int, lineas_log: Optional[Sequence[str]]) -> str:
    """/log n: las últimas n líneas que el llamante leyó (esta función no toca disco)."""
    if lineas_log is None:
        return "Log no disponible"
    ultimas = list(lineas_log)[-n:] if n > 0 else []
    filas = [_titulo(f"Log (últimas {len(ultimas)})")] + [_esc(str(l).rstrip()[:300]) for l in ultimas]
    return "\n".join(filas)


# ═══════════════════════════ red: Telegram ═════════════════════════════
def _contexto_ssl() -> Optional[ssl.SSLContext]:
    """SSL con el almacén de Windows (bot_alerts_telegram l.41-62: Avast sustituye el certificado)."""
    try:
        ctx = ssl.create_default_context()
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
        return ctx
    except Exception:  # noqa: BLE001 — frontera: sin almacén del sistema se prueba certifi y, si no, el defecto de urllib
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except Exception:  # noqa: BLE001 — ídem
            return None


def _sin_token(texto: str, token: str) -> str:
    """Tapa el token (valor literal y forma URL) en un texto de error antes de loguearlo (R-Q-01)."""
    limpio = texto.replace(token, MASCARA) if token else texto
    return _PATRON_TOKEN_URL.sub(MASCARA, limpio)


def _epoch_de(t: Any) -> Optional[float]:
    """Epoch de un número o de un ISO 8601 con zona; None si no se entiende (o sin zona)."""
    if isinstance(t, bool):
        return None
    if isinstance(t, (int, float)):
        return float(t)
    if isinstance(t, str):
        try:
            dt = datetime.fromisoformat(t.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt.timestamp() if dt.tzinfo is not None else None
    return None


class ReceptorTelegram:
    """getUpdates por long polling → `al_comando(Comando)` (R-M-04, R-Q-01; §3.10, §6.1 hilo «telegram-recibo»).

    HiloVigilado; `urllib` (nunca httpx: la URL lleva el token); `offset` =
    último update_id + 1 (confirma lo leído). C-02: con `ruta_offset`
    (`estado/telegram_offset`, lo pasa el ejecutor) el offset y el último
    update_id se persisten de forma atómica ANTES de entregar cada comando y
    se cargan al construir: tras un reinicio rápido no se repite el último
    «/cerrar X N SI» (los update_id < offset se ignoran), y `parar()` hace un
    getUpdates final con timeout 0 para que Telegram dé lo leído por
    confirmado. Sin `ruta_offset` el offset vive solo en memoria (tests).
    Filtra el chat_id ANTES de
    parsear; ignora lo que no sea un mensaje de texto (fotos, ediciones) y
    los mensajes más viejos que `caducidad_s` (reinicio con cola vieja).
    Nunca lanza por red: registra el error sin la URL, espera
    `espera_error_s` (interrumpible) y vuelve a preguntar. Trampa: si otro
    proceso (el bot de alertas viejo) hace getUpdates con el MISMO token,
    Telegram contesta 409; se registra y se sigue reintentando.
    """

    def __init__(self, token: str, autorizados: frozenset[int], al_comando: Callable[[Comando], None], reloj,
                 *, api: str = API_TELEGRAM, espera_polling_s: int = ESPERA_POLLING_S,
                 caducidad_s: float = CADUCIDAD_COMANDO_S, espera_error_s: float = ESPERA_ERROR_RED_S,
                 al_caida: Optional[Callable[[str, str, bool], None]] = None,
                 ruta_offset: Optional[Path] = None) -> None:
        if not token:
            raise ValueError("ReceptorTelegram necesita un token")
        self._token = token
        self._autorizados = frozenset(autorizados)
        self._al_comando = al_comando
        self._reloj = reloj
        self._api = api.rstrip("/")
        self._espera_polling_s = int(espera_polling_s)
        self._caducidad_s = float(caducidad_s)
        self._espera_error_s = float(espera_error_s)
        self._ssl = _contexto_ssl() if self._api.startswith("https") else None
        self.offset = 0
        self.ultimo_update_id: Optional[int] = None
        self.errores = 0
        self.entregados = 0
        self._ruta_offset = Path(ruta_offset) if ruta_offset is not None else None
        self._cargar_offset()
        self._hilo = HiloVigilado("telegram-recibo", self._cuerpo, al_caida or _al_caida_log)

    def arrancar(self) -> None:
        self._hilo.arrancar()

    def parar(self, espera_s: float = 5.0) -> None:
        """Para el hilo y hace un getUpdates FINAL (timeout 0) con el offset: Telegram da por leído lo entregado (C-02).

        Sin ese sondeo, Telegram guarda como no leído el último lote entregado
        y lo devolvería al arrancar (el «/cerrar X N SI» se repetiría).
        """
        self._hilo.parar(espera_s)
        if self.offset > 0:
            if self._get_updates(timeout_s=0, limite=1) is None:
                logger.warning("[COMANDOS] no se pudo confirmar a Telegram lo leído al parar; queda el offset en disco")

    # ── offset persistido (C-02) ──
    def _cargar_offset(self) -> None:
        """Lee `estado/telegram_offset` si existe: lo ya entregado no se vuelve a entregar tras un reinicio (C-02)."""
        if self._ruta_offset is None:
            return
        try:
            datos = json.loads(self._ruta_offset.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:  # noqa: BLE001 — frontera de fichero: sin estado se empieza de 0 (la caducidad protege)
            logger.warning("[COMANDOS] %s ilegible (%s): se empieza sin offset", self._ruta_offset.name, exc)
            return
        if not isinstance(datos, dict):
            return
        offset = datos.get("offset")
        if type(offset) is int and offset >= 0:
            self.offset = offset
        ultimo = datos.get("ultimo_update_id")
        if type(ultimo) is int:
            self.ultimo_update_id = ultimo

    def _guardar_offset(self) -> None:
        """Escritura atómica (tmp + replace) de {offset, ultimo_update_id}, ANTES de entregar (como mucho una vez)."""
        if self._ruta_offset is None:
            return
        tmp = self._ruta_offset.with_name(self._ruta_offset.name + ".tmp")
        try:
            tmp.write_text(json.dumps({"offset": self.offset, "ultimo_update_id": self.ultimo_update_id}),
                           encoding="utf-8")
            tmp.replace(self._ruta_offset)
        except OSError as exc:  # noqa: BLE001 — frontera de fichero: se sigue; en memoria el offset ya avanzó
            logger.warning("[COMANDOS] no puedo guardar %s: %s", self._ruta_offset.name, exc)

    @property
    def vivo(self) -> bool:
        return self._hilo.vivo

    def _cuerpo(self) -> None:
        while not self._hilo.parando.is_set():
            inicio = time.monotonic()
            entregados = self.sondear()
            if entregados is None:
                self._hilo.parando.wait(self._espera_error_s)
            elif time.monotonic() - inicio < RONDA_MIN_S:
                # un servidor que contesta al instante (sin long polling) no puede poner el hilo a girar en vacío
                self._hilo.parando.wait(RONDA_MIN_S)

    def sondear(self) -> Optional[int]:
        """Una ronda de getUpdates. Devuelve cuántos comandos entregó, o None si no se pudo preguntar."""
        datos = self._get_updates()
        if datos is None:
            return None
        entregados = 0
        avanzado = False
        for u in datos:
            if not isinstance(u, dict):
                continue
            uid = u.get("update_id")
            if type(uid) is int:
                if uid < self.offset:
                    # C-02: ya entregado (offset persistido); Telegram lo repite si no llegó a confirmarlo
                    logger.info("[COMANDOS] update %d ya entregado antes: se ignora", uid)
                    continue
                self.offset = uid + 1
                self.ultimo_update_id = uid
                avanzado = True
            comando = self._comando_de(u)
            if comando is None:
                continue
            self._guardar_offset()      # C-02: consta como leído ANTES de entregarlo (como mucho una vez)
            avanzado = False
            try:
                self._al_comando(comando)
                entregados += 1
                self.entregados += 1
            except Exception as exc:  # noqa: BLE001 — frontera de callback: un al_comando que falla no para el receptor
                logger.error("[COMANDOS] al_comando falló con /%s: %s", comando.nombre, exc)
        if avanzado:
            self._guardar_offset()      # updates sin comando (fotos, chats ajenos): también constan como leídos
        return entregados

    def _comando_de(self, u: dict) -> Optional[Comando]:
        m = u.get("message")
        if not isinstance(m, dict):
            return None
        chat = m.get("chat") if isinstance(m.get("chat"), dict) else {}
        chat_id = chat.get("id")
        if type(chat_id) is not int or chat_id not in self._autorizados:
            logger.warning("[COMANDOS] mensaje de un chat no autorizado (%s) ignorado", chat_id)
            return None
        texto = m.get("text")
        if not isinstance(texto, str) or not texto.strip():
            return None
        fecha = m.get("date")
        if type(fecha) is int and self._reloj.epoch() - fecha > self._caducidad_s:
            logger.warning("[COMANDOS] mensaje de hace %.0f s descartado por viejo", self._reloj.epoch() - fecha)
            return None
        return parsear(texto, chat_id, self._autorizados, id_comando=f"tg:{u.get('update_id')}")

    def _get_updates(self, timeout_s: Optional[int] = None, limite: Optional[int] = None) -> Optional[list]:
        espera = self._espera_polling_s if timeout_s is None else int(timeout_s)
        parametros: dict[str, Any] = {"offset": self.offset, "timeout": espera, "allowed_updates": '["message"]'}
        if limite is not None:
            parametros["limit"] = int(limite)
        consulta = urllib.parse.urlencode(parametros)
        peticion = urllib.request.Request(f"{self._api}/bot{self._token}/getUpdates?{consulta}", method="GET")
        try:
            with urllib.request.urlopen(peticion, timeout=espera + 10, context=self._ssl) as r:
                cuerpo = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # noqa: BLE001 — frontera de red (R-Q-01: sin URL en el log)
            self.errores += 1
            logger.warning("[COMANDOS] getUpdates HTTP %s%s", exc.code,
                           " (otro proceso lee con el mismo token)" if exc.code == 409 else "")
            return None
        except Exception as exc:  # noqa: BLE001 — frontera de red: nunca lanza; el error va sin la URL
            self.errores += 1
            logger.warning("[COMANDOS] getUpdates falló: %s", _sin_token(f"{type(exc).__name__}: {exc}", self._token))
            return None
        if not isinstance(cuerpo, dict) or cuerpo.get("ok") is not True or not isinstance(cuerpo.get("result"), list):
            self.errores += 1
            logger.warning("[COMANDOS] getUpdates respuesta inesperada")
            return None
        return cuerpo["result"]


def _al_caida_log(nombre: str, error: str, relanzado: bool) -> None:
    logger.error("[COMANDOS] hilo %s caído (%s); relanzado=%s", nombre, error, relanzado)


# ═══════════════════════════ fichero del cuadro ════════════════════════
class LectorComandosFichero:
    """Botones del cuadro: `estado/comandos.jsonl` → `al_comando(Comando)` (§3.10, §7, R-B-07, R-M-03).

    Cada línea: {"id","comando","args","quien","t"} con `t` epoch o ISO con
    zona. `id` único → idempotente: se persisten `offset` y `ultimo_id` en
    `estado/comandos_leidos` ANTES de entregar (como mucho una vez) y se
    ignoran ids repetidos. Lee cada `intervalo_s` las líneas nuevas desde el
    offset, solo hasta el último «\\n» (línea partida → la próxima vuelta).
    Si el fichero encoge (lo rotaron), se relee desde el principio saltando
    hasta `ultimo_id`. Comandos más viejos que `caducidad_s` o sin `t`
    legible se descartan. `Comando.chat_id` = 0 y `requiere` = "confirmado"
    (el botón es la confirmación) o "nada" en consultas.
    """

    def __init__(self, ruta: Path, al_comando: Callable[[Comando], None], reloj, *,
                 intervalo_s: float = LECTURA_FICHERO_S, caducidad_s: float = CADUCIDAD_COMANDO_S,
                 al_caida: Optional[Callable[[str, str, bool], None]] = None) -> None:
        self._ruta = Path(ruta)
        self._ruta_leidos = self._ruta.parent / "comandos_leidos"
        self._al_comando = al_comando
        self._reloj = reloj
        self._intervalo_s = float(intervalo_s)
        self._caducidad_s = float(caducidad_s)
        self._offset = 0
        self._ultimo_id: Optional[str] = None
        self._vistos: set[str] = set()
        self._cargado = False
        self.entregados = 0
        self.descartados = 0
        self._hilo = HiloVigilado("comandos-fichero", self._cuerpo, al_caida or _al_caida_log)

    def arrancar(self) -> None:
        self._hilo.arrancar()

    def parar(self, espera_s: float = 5.0) -> None:
        self._hilo.parar(espera_s)

    @property
    def vivo(self) -> bool:
        return self._hilo.vivo

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def ultimo_id(self) -> Optional[str]:
        return self._ultimo_id

    def _cuerpo(self) -> None:
        while not self._hilo.parando.is_set():
            self.leer_ahora()
            self._hilo.parando.wait(self._intervalo_s)

    def leer_ahora(self) -> int:
        """Procesa las líneas completas nuevas; devuelve cuántos comandos entregó. Nunca lanza por el fichero."""
        if not self._cargado:
            self._cargar_leidos()
        try:
            tamano = self._ruta.stat().st_size
        except FileNotFoundError:
            return 0
        except OSError as exc:  # noqa: BLE001 — frontera de fichero
            logger.warning("[COMANDOS] no puedo mirar %s: %s", self._ruta.name, exc)
            return 0
        saltar_hasta: Optional[str] = None
        if tamano < self._offset:
            logger.warning("[COMANDOS] %s ha encogido: se relee saltando hasta %s", self._ruta.name, self._ultimo_id)
            self._offset = 0
            saltar_hasta = self._ultimo_id if self._ultimo_id is not None and self._contiene(self._ultimo_id) else None
        if tamano == self._offset:
            return 0
        try:
            with self._ruta.open("rb") as f:
                f.seek(self._offset)
                bloque = f.read(tamano - self._offset)
        except OSError as exc:  # noqa: BLE001 — frontera de fichero
            logger.warning("[COMANDOS] no puedo leer %s: %s", self._ruta.name, exc)
            return 0
        corte = bloque.rfind(b"\n")
        if corte < 0:
            return 0
        entregados = 0
        posicion = self._offset
        for cruda in bloque[:corte + 1].split(b"\n")[:-1]:
            posicion += len(cruda) + 1
            registro = self._interpretar(cruda)
            ident = registro.get("id") if registro is not None else None
            if saltar_hasta is not None:
                if ident == saltar_hasta:
                    saltar_hasta = None
                self._offset = posicion
                continue
            comando = self._comando_de(registro) if registro is not None else None
            self._offset = posicion
            if comando is not None:
                self._ultimo_id = str(registro["id"])
                self._vistos.add(self._ultimo_id)
            self._guardar_leidos()
            if comando is None:
                continue
            try:
                self._al_comando(comando)
                entregados += 1
                self.entregados += 1
            except Exception as exc:  # noqa: BLE001 — frontera de callback: se registra y se sigue (ya consta como leído)
                logger.error("[COMANDOS] al_comando falló con /%s: %s", comando.nombre, exc)
        return entregados

    def _interpretar(self, cruda: bytes) -> Optional[dict]:
        texto = cruda.decode("utf-8", errors="replace").strip()
        if not texto:
            return None
        try:
            registro = json.loads(texto)
        except ValueError:
            self.descartados += 1
            logger.warning("[COMANDOS] línea no JSON en %s descartada (%d bytes)", self._ruta.name, len(cruda))
            return None
        if not isinstance(registro, dict):
            self.descartados += 1
            return None
        ident = registro.get("id")
        if isinstance(ident, bool) or not isinstance(ident, (str, int)) or str(ident) == "":
            self.descartados += 1
            logger.warning("[COMANDOS] comando sin id descartado")
            return None
        registro["id"] = str(ident)
        return registro

    def _comando_de(self, registro: dict) -> Optional[Comando]:
        ident = registro["id"]
        if ident in self._vistos:
            logger.info("[COMANDOS] id %s repetido: ya se procesó", ident)
            return None
        nombre = registro.get("comando")
        args_crudos = registro.get("args", [])
        if args_crudos is None:
            args_crudos = []
        if not isinstance(nombre, str) or not isinstance(args_crudos, list):
            self.descartados += 1
            logger.warning("[COMANDOS] comando %s mal formado descartado", ident)
            return None
        t = _epoch_de(registro.get("t"))
        if t is None or self._reloj.epoch() - t > self._caducidad_s:
            self.descartados += 1
            self._vistos.add(ident)
            logger.warning("[COMANDOS] comando %s descartado: %s", ident, "sin hora" if t is None else "viejo")
            return None
        args = [str(a).strip() for a in args_crudos if not isinstance(a, (dict, list)) and str(a).strip()]
        nombre = nombre.strip().lstrip("/").lower()
        quien = str(registro.get("quien") or "?")[:ARG_MAX_CARACTERES]
        texto = " ".join(["/" + nombre, *args]) + f" (cuadro: {quien})"
        logger.info("[COMANDOS] botón /%s de %s (id %s)", nombre, quien, ident)
        return _construir(nombre, args, CHAT_ID_CUADRO, f"cuadro:{ident}", texto, desde_cuadro=True)

    def _contiene(self, ident: str) -> bool:
        try:
            with self._ruta.open("rb") as f:
                for cruda in f:
                    registro = self._interpretar(cruda)
                    if registro is not None and registro["id"] == ident:
                        return True
        except OSError:  # noqa: BLE001 — frontera de fichero
            return False
        return False

    def _cargar_leidos(self) -> None:
        self._cargado = True
        try:
            datos = json.loads(self._ruta_leidos.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:  # noqa: BLE001 — frontera de fichero: sin estado se empieza de 0 (la caducidad protege)
            logger.warning("[COMANDOS] %s ilegible (%s): se empieza desde el principio", self._ruta_leidos.name, exc)
            return
        if not isinstance(datos, dict):
            return
        offset = datos.get("offset")
        if type(offset) is int and offset >= 0:
            self._offset = offset
        ultimo = datos.get("ultimo_id")
        if isinstance(ultimo, str) and ultimo:
            self._ultimo_id = ultimo
            self._vistos.add(ultimo)

    def _guardar_leidos(self) -> None:
        tmp = self._ruta_leidos.with_name(self._ruta_leidos.name + ".tmp")
        try:
            tmp.write_text(json.dumps({"offset": self._offset, "ultimo_id": self._ultimo_id}), encoding="utf-8")
            tmp.replace(self._ruta_leidos)
        except OSError as exc:  # noqa: BLE001 — frontera de fichero: se sigue; en memoria el id ya consta como visto
            logger.warning("[COMANDOS] no puedo guardar %s: %s", self._ruta_leidos.name, exc)


__all__ = [
    "API_TELEGRAM", "CADUCIDAD_COMANDO_S", "CHAT_ID_CUADRO", "CONFIRMAR", "CONSULTA", "CON_SI", "DOS_PASOS",
    "EJECUTABLES", "ESPERA_POLLING_S", "FICHERO_OFFSET_TELEGRAM", "LECTURA_FICHERO_S", "LOG_LINEAS_DEFECTO", "LOG_LINEAS_MAX",
    "REQUIERE_ARGS_INVALIDOS", "REQUIERE_CONFIRMACION", "REQUIERE_CONFIRMADO", "REQUIERE_CONFIRMAR",
    "REQUIERE_DESCONOCIDO", "REQUIERE_NADA", "REQUIERE_SI", "REQUIERE_SI_FALTANTE", "TTL_CONFIRMACION_S", "USO",
    "Confirmaciones", "LectorComandosFichero", "ReceptorTelegram", "parsear", "respuesta_previa",
    "responder_consulta",
]
