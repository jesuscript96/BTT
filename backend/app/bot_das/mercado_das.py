"""Libro de `$Quote` incremental, estado del símbolo, bandas LDLU y suscripciones Lv1 con tope.

QUÉ HACE. `MercadoDAS` guarda por ticker la cotización que DAS va parcheando
(`$Quote` solo trae los campos que cambian, manual L1268-1269), el estado del
símbolo (`$IssueStatus`: SSR y halt; `$LDLU`: bandas; `$SHORTINFO`), cuenta
los halts UP del día (k de R-F-01) en `marcar_halt`, decide qué símbolos
suscribir con el tope de Lv1 del API (100, manual L1996) y prioridad
posiciones > intentos > radar, y ofrece `fresca`, `dollar_volume` (V × VWAP
para el modo de seguridad, R-I-04, pregunta 9) y `sin_cotizacion_desde` (A7:
símbolo que no casa entre Massive y DAS).

POR QUÉ ESTÁ AQUÍ. Los precios de ejecución salen de DAS en tiempo real
(R-A-06.3) y las bandas LULD solo las da DAS (R-F-02). Vive en el hilo del
decisor: ningún otro hilo lo toca (§6.1, un solo mutador), por eso no lleva
cerrojos. Importarlo no ejecuta nada.

LAS TRAMPAS.
  * Riesgo 15: un `$Quote` con solo `V:` NO significa bid/ask nulos. Se aplica
    como parche: las claves ausentes conservan su valor. Pero `B:0`/`A:0`
    explícitos (halt, tras las 20:00) SÍ borran el bid/ask: un precio 0 no es
    un precio y `fresca()` debe decir que no hay cotización.
  * Valores no numéricos («A:», «L:abc», «NaN») se ignoran sin tocar lo
    anterior; nunca se hace aritmética con floats: `Decimal(cadena)`. Las
    claves se comparan sin distinguir mayúsculas (el manual escribe `VWAP`,
    `Hi`, `Asz`; ninguna colisiona al pasarla a minúsculas) y las que no se
    conocen (`op`, `ycl`, `tcl`, `PE`, `RVOL`, `tradesAllDay`…) se ignoran.
  * `fresca()` mira `actualizada_en` (monotónico del reloj inyectado), no la
    hora del servidor; y un libro cruzado (ask < bid) no es fresco: la
    aritmética de `reglas.precios` lanzaría con él.
  * k cuenta SOLO halts UP en RTH (R-F-01): `last` ≥ limit_up · (1 − 0,5 %) y
    franja «RTH». Un halt en premercado (T1/T12) o un halt DOWN no suman. k
    incluye los halts anteriores a nuestra entrada: se cuenta desde que el
    ticker entra en el libro, no desde el primer fill.
  * `marcar_halt` decide la transición por `halt_desde`, no por el `ta`
    anterior: da igual si el decisor llamó antes a `aplicar` con el mismo
    mensaje. `$IssueStatus` repetido con `H` → None (sin transición) y la
    guardia `orden_open_enviada` se conserva (injerto A §8.23).
  * `suscripciones` aplica el tope sobre el conjunto DESEADO ordenado por
    prioridad; lo que no cabe se cuenta (`descartados_por_tope`) y sale en la
    foto. Tras una reconexión de DAS hay que llamar a `reiniciar_suscripciones`
    (las suscripciones no sobreviven al socket).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from app.bot_das.reglas.precios import de_float
from app.bot_das.reloj import ET, hora_das_a_et
from app.bot_das.tipos import (
    MAX_LV1,
    Cotizacion,
    EstadoSimbolo,
    MensajeDAS,
    MsgIssueStatus,
    MsgLDLU,
    MsgQuote,
    MsgShortInfo,
)

TOLERANCIA_BANDA_PCT = Decimal("0.5")   # técnico: el último print antes del halt puede quedar un tick bajo la banda
FRESCA_MAX_S = 5.0                      # §3.12: defecto de `fresca` y `sin_cotizacion_desde`
_CIEN = Decimal("100")
_CAMPOS_PRECIO = {"a": "ask", "b": "bid", "l": "last", "hi": "hi", "lo": "lo", "vwap": "vwap"}   # manual L1248-1316, en minúsculas
_CAMPOS_ENTERO = {"asz": "asz", "bsz": "bsz", "v": "volumen"}
_CAMPO_HORA = "t"
_GRUPOS_SUSCRIPCION = ("posiciones", "intentos", "radar")   # prioridad, de mayor a menor


class MercadoDAS:
    """El mercado visto desde DAS para UN proceso (el decisor). Sin hilos, sin red."""

    def __init__(self, reloj, max_lv1: int = MAX_LV1, tolerancia_banda_pct: Decimal = TOLERANCIA_BANDA_PCT) -> None:
        if isinstance(max_lv1, bool) or int(max_lv1) != max_lv1 or max_lv1 <= 0:
            raise ValueError(f"max_lv1 debe ser un entero > 0: {max_lv1!r}")
        self._reloj = reloj
        self._max_lv1 = int(max_lv1)
        self._tolerancia = de_float(tolerancia_banda_pct)
        if self._tolerancia < 0:
            raise ValueError(f"tolerancia_banda_pct debe ser ≥ 0: {tolerancia_banda_pct!r}")
        self._cotizaciones: dict[str, Cotizacion] = {}
        self._simbolos: dict[str, EstadoSimbolo] = {}
        self._suscritos: dict[str, float] = {}      # ticker → mono() de la suscripción
        self._descartados = 0
        self._quotes = 0
        self._campos_ignorados = 0

    # ── mensajes de DAS ─────────────────────────────────────────────────
    def aplicar(self, msg: MensajeDAS) -> Optional[str]:
        """Aplica `MsgQuote` (parche), `MsgIssueStatus`, `MsgLDLU` o `MsgShortInfo`; devuelve el ticker tocado o None.

        Otros mensajes se ignoran (None). `MsgIssueStatus` aquí solo actualiza
        SSR/TA/TAT; la transición de halt y k los lleva `marcar_halt`.
        """
        if isinstance(msg, MsgQuote):
            return self._aplicar_quote(msg)
        if not isinstance(msg, (MsgIssueStatus, MsgLDLU, MsgShortInfo)) or not _norm(msg.ticker):
            return None
        if isinstance(msg, MsgIssueStatus):
            simb = self.simbolo(msg.ticker)
            self._aplicar_estado(simb, msg)
            return simb.ticker
        if isinstance(msg, MsgLDLU):
            simb = self.simbolo(msg.ticker)
            simb.limit_down = _precio_o_none(msg.limit_down)
            simb.limit_up = _precio_o_none(msg.limit_up)
            simb.consultado_en = self._reloj.mono()
            return simb.ticker
        if isinstance(msg, MsgShortInfo):
            simb = self.simbolo(msg.ticker)
            simb.shortable = msg.shortable
            simb.tasa_corta = msg.tasa_corta
            simb.reg_sho = msg.reg_sho
            simb.consultado_en = self._reloj.mono()
            return simb.ticker
        return None

    def _aplicar_quote(self, msg: MsgQuote) -> Optional[str]:
        """Parche de `$Quote` (manual L1248-1316): solo las claves presentes; `Decimal(cadena)`; sin tocar lo que no viene."""
        ticker = _norm(msg.ticker)
        if not ticker:
            return None
        cot = self._cotizaciones.get(ticker)
        if cot is None:
            cot = Cotizacion(ticker=ticker)
            self._cotizaciones[ticker] = cot
        for clave_cruda, valor in msg.campos.items():
            clave = str(clave_cruda).strip().lower()
            if clave in _CAMPOS_PRECIO:
                precio = _decimal_o_none(valor)
                if precio is None:
                    self._campos_ignorados += 1
                    continue
                setattr(cot, _CAMPOS_PRECIO[clave], precio if precio > 0 else None)
            elif clave in _CAMPOS_ENTERO:
                entero = _entero_o_none(valor)
                if entero is None:
                    self._campos_ignorados += 1
                    continue
                setattr(cot, _CAMPOS_ENTERO[clave], entero)
            elif clave == _CAMPO_HORA:
                cot.hora_servidor = str(valor).strip() or None
            # op, ycl, tcl, PE, RVOL, tradesAllDay y claves futuras: se ignoran (especificación §3.10)
        cot.actualizada_en = self._reloj.mono()
        self._quotes += 1
        return ticker

    def _aplicar_estado(self, simb: EstadoSimbolo, msg: MsgIssueStatus) -> None:
        if msg.ssr is not None:
            simb.ssr = msg.ssr
        simb.ta = msg.ta
        simb.tat = msg.tat
        simb.consultado_en = self._reloj.mono()

    # ── lecturas ────────────────────────────────────────────────────────
    def cotizacion(self, ticker: str) -> Optional[Cotizacion]:
        """La cotización acumulada del ticker, o None si DAS nunca habló de él."""
        return self._cotizaciones.get(_norm(ticker))

    def simbolo(self, ticker: str) -> EstadoSimbolo:
        """El estado del símbolo (se crea vacío la primera vez: k = 0, sin halt, sin bandas)."""
        clave = _norm(ticker)
        simb = self._simbolos.get(clave)
        if simb is None:
            simb = EstadoSimbolo(ticker=clave)
            self._simbolos[clave] = simb
        return simb

    def fresca(self, ticker: str, ahora: float, max_s: float = FRESCA_MAX_S) -> bool:
        """True si hay bid y ask (> 0, no cruzados) y el último `$Quote` llegó hace ≤ `max_s` s (monotónico)."""
        cot = self.cotizacion(ticker)
        if cot is None or cot.bid is None or cot.ask is None or cot.actualizada_en is None:
            return False
        if cot.ask < cot.bid:
            return False
        return ahora - cot.actualizada_en <= max_s

    def dollar_volume(self, ticker: str) -> Optional[Decimal]:
        """Dólares negociados desde las 04:00 ≈ V × VWAP del `$Quote` (R-I-04, pregunta 9); None si falta alguno."""
        cot = self.cotizacion(ticker)
        if cot is None or cot.volumen is None or cot.vwap is None or cot.vwap <= 0:
            return None
        return Decimal(cot.volumen) * cot.vwap

    # ── halts (R-F-01) ──────────────────────────────────────────────────
    def marcar_halt(self, ticker: str, msg: MsgIssueStatus, ahora: datetime, last: Optional[Decimal],
                    franja: str) -> Optional[str]:
        """Transición del símbolo con un `$IssueStatus`: «halt» (nuevo), «reapertura» (TA Q/T/ausente tras un halt) o None.

        En un halt nuevo guarda `halt_desde` (TAT del mensaje si es válido, si
        no `ahora`), `precio_parada` (`last` o el último del libro), pone
        `orden_open_enviada = False` y suma k SOLO si es UP (`last` ≥ limit_up
        · (1 − tolerancia)) y la franja es RTH. En la reapertura borra
        `halt_desde` y la guardia; `precio_parada` se conserva para medir la
        subida (R-F-05) hasta el siguiente halt.
        """
        simb = self.simbolo(ticker)
        self._aplicar_estado(simb, msg)
        parado = msg.ta in ("H", "P")
        if parado and simb.halt_desde is None:
            simb.halt_desde = self._inicio_halt(msg.tat, ahora)
            precio = last if last is not None else self._ultimo_precio(simb.ticker)
            simb.precio_parada = _precio_o_none(precio)
            simb.orden_open_enviada = False
            if franja.startswith("RTH") and self._es_halt_up(simb.precio_parada, simb.limit_up):
                simb.k_halts_up += 1
            return "halt"
        if not parado and simb.halt_desde is not None:
            simb.halt_desde = None
            simb.orden_open_enviada = False
            return "reapertura"
        return None

    def _inicio_halt(self, tat: Optional[str], ahora: datetime) -> datetime:
        ahora_et = ahora.replace(tzinfo=ET) if ahora.tzinfo is None else ahora.astimezone(ET)
        if tat:
            try:
                return hora_das_a_et(tat, ahora_et.date())
            except ValueError:
                pass
        return ahora_et

    def _ultimo_precio(self, ticker: str) -> Optional[Decimal]:
        cot = self._cotizaciones.get(ticker)
        return cot.last if cot is not None else None

    def _es_halt_up(self, precio: Optional[Decimal], limit_up: Optional[Decimal]) -> bool:
        if precio is None or limit_up is None or limit_up <= 0:
            return False
        return precio >= limit_up * (_CIEN - self._tolerancia) / _CIEN

    # ── suscripciones Lv1 (manual L1996: 100 símbolos) ──────────────────
    def suscripciones(self, posiciones: Iterable[str] | dict, intentos: Iterable[str] = (),
                      radar: Iterable[str] = ()) -> tuple[list[str], list[str]]:
        """(altas, bajas) para llegar al conjunto deseado con tope `max_lv1` y prioridad posiciones > intentos > radar.

        Firma elegida (el documento deja «necesarios» abierto): tres colecciones
        de tickers, o un solo `dict` con las claves «posiciones», «intentos» y
        «radar» (cualquier otra clave es un error: ValueError; un `str` suelto
        como grupo, TypeError, porque se iteraría letra a letra; en los dos
        casos no se toca el estado). Llamar con una
        sola colección la trata como máxima prioridad. Dentro de cada grupo el
        orden es alfabético (determinista). Las altas salen en orden de
        prioridad; se anotan como suscritas con el monotónico de ahora
        (`suscrito_en`) y las bajas se olvidan. Idempotente: repetir la llamada
        con lo mismo devuelve ([], []).
        """
        if isinstance(posiciones, dict):
            desconocidas = set(posiciones) - set(_GRUPOS_SUSCRIPCION)
            if desconocidas:
                raise ValueError(f"grupos de suscripción desconocidos: {sorted(desconocidas)}")
            grupos: tuple[Iterable[str], ...] = tuple(posiciones.get(g, ()) for g in _GRUPOS_SUSCRIPCION)
        else:
            grupos = (posiciones, intentos, radar)
        deseados: list[str] = []
        for grupo in grupos:
            for ticker in sorted(_como_tickers(grupo)):
                if ticker not in deseados:
                    deseados.append(ticker)
        caben = deseados[: self._max_lv1]
        objetivo = set(caben)
        altas = [t for t in caben if t not in self._suscritos]
        bajas = sorted(t for t in self._suscritos if t not in objetivo)
        ahora = self._reloj.mono()
        for ticker in bajas:
            del self._suscritos[ticker]
        for ticker in altas:
            self._suscritos[ticker] = ahora
        self._descartados = len(deseados) - len(caben)
        return altas, bajas

    def suscritos(self) -> list[str]:
        """Tickers que este libro cree suscritos, ordenados."""
        return sorted(self._suscritos)

    def suscrito_en(self, ticker: str) -> Optional[float]:
        """Monotónico en que se pidió el alta del ticker (para `sin_cotizacion_desde`), o None si no está suscrito."""
        return self._suscritos.get(_norm(ticker))

    def reiniciar_suscripciones(self) -> None:
        """Tras reconectar con DAS (R-J-02) el socket nuevo no tiene suscripciones: el siguiente `suscripciones` las repite."""
        self._suscritos.clear()

    def sin_cotizacion_desde(self, ticker: str, suscrito_en: float, ahora: float, max_s: float = FRESCA_MAX_S) -> bool:
        """A7: True si pasaron ≥ `max_s` s desde la suscripción y no llegó NINGÚN `$Quote` posterior (símbolo que no casa)."""
        if ahora - suscrito_en < max_s:
            return False
        cot = self.cotizacion(ticker)
        return cot is None or cot.actualizada_en is None or cot.actualizada_en < suscrito_en

    # ── foto para estado/foto.json (panel 4.4) ──────────────────────────
    def foto(self) -> dict:
        """Resumen serializable a JSON: contadores, suscritos con su cotización y los símbolos con halt o k > 0."""
        tickers = {}
        for ticker in sorted(self._suscritos):
            cot = self._cotizaciones.get(ticker)
            tickers[ticker] = {
                "suscrito_en": self._suscritos[ticker],
                "bid": _txt(cot.bid) if cot else None,
                "ask": _txt(cot.ask) if cot else None,
                "last": _txt(cot.last) if cot else None,
                "volumen": cot.volumen if cot else None,
                "actualizada_en": cot.actualizada_en if cot else None,
            }
        halts = {}
        for ticker, simb in sorted(self._simbolos.items()):
            if simb.halt_desde is None and simb.k_halts_up == 0:
                continue
            halts[ticker] = {
                "ta": simb.ta,
                "tat": simb.tat,
                "halt_desde": simb.halt_desde.isoformat() if simb.halt_desde else None,
                "k_halts_up": simb.k_halts_up,
                "precio_parada": _txt(simb.precio_parada),
                "limit_down": _txt(simb.limit_down),
                "limit_up": _txt(simb.limit_up),
                "orden_open_enviada": simb.orden_open_enviada,
            }
        return {
            "max_lv1": self._max_lv1,
            "suscritos": len(self._suscritos),
            "descartados_por_tope": self._descartados,
            "cotizaciones": len(self._cotizaciones),
            "quotes_aplicadas": self._quotes,
            "campos_ignorados": self._campos_ignorados,
            "tickers": tickers,
            "halts": halts,
        }


# ── auxiliares ──────────────────────────────────────────────────────────
def _norm(ticker: object) -> str:
    return str(ticker).strip().upper()


def _decimal_o_none(valor: object) -> Optional[Decimal]:
    """`Decimal(cadena)` tolerante: None si no es numérico o no es finito (NaN/Infinity)."""
    try:
        resultado = Decimal(str(valor).strip())
    except (InvalidOperation, ValueError):
        return None
    return resultado if resultado.is_finite() else None


def _entero_o_none(valor: object) -> Optional[int]:
    """Tamaños y volumen: entero ≥ 0; None si no lo es (se ignora el campo)."""
    decimal = _decimal_o_none(valor)
    if decimal is None or decimal < 0 or decimal != decimal.to_integral_value():
        return None
    return int(decimal)


def _precio_o_none(valor: object) -> Optional[Decimal]:
    """Precio válido (> 0 y finito) o None. Un float o texto se convierte UNA vez con `Decimal(str(x))`."""
    if valor is None or isinstance(valor, bool):
        return None
    precio = valor if isinstance(valor, Decimal) else _decimal_o_none(valor)
    if precio is None or not precio.is_finite() or precio <= 0:
        return None
    return precio


def _como_tickers(grupo: object) -> set[str]:
    """Una colección de tickers normalizados. Un `str` suelto es un error (se iteraría letra a letra)."""
    if isinstance(grupo, (str, bytes)):
        raise TypeError(f"se esperaba una colección de tickers, no un texto: {grupo!r}")
    return {_norm(t) for t in grupo if _norm(t)}


def _txt(valor: Optional[Decimal]) -> Optional[str]:
    return None if valor is None else str(valor)
