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
  * k cuenta SOLO halts UP en RTH (R-F-01). E1-06: infracontar k es el lado
    peligroso para un corto, así que en una pausa LULD (`TA:P`) se clasifica
    por CERCANÍA (precio de parada más cerca de limit_up que de limit_down, o
    en el medio → UP) y, sin las dos bandas, cuenta como UP (anotado en
    `clasificacion_halt`). En un `TA:H` (T1/T12, no LULD) sigue la regla de la
    banda: precio ≥ limit_up · (1 − 0,5 %); sin banda no suma. Un halt en
    premercado o un halt DOWN no suman. k incluye los halts anteriores a
    nuestra entrada: se cuenta desde que el ticker entra en el libro, y
    `sembrar_k` lo repone tras un reinicio (E1-03, nunca lo baja).
  * `marcar_halt` decide la transición por `halt_desde`, no por el `ta`
    anterior: da igual si el decisor llamó antes a `aplicar` con el mismo
    mensaje. `$IssueStatus` repetido con `H` → None (sin transición) y la
    guardia `orden_open_enviada` se conserva (injerto A §8.23). E1-05: `Q`
    (solo cotización antes del cruce) sigue PARADO; se reabre con `T` o sin
    TA. E1-10: el TA se normaliza aquí (sin espacios, en mayúsculas) y se
    guarda así en `EstadoSimbolo.ta`: `reglas.halts` y este módulo ven lo
    mismo.
  * `velas_minuto` (E1-08) arma velas de 1 min con los `$Quote` (máximo,
    mínimo del `last` y dólares = Δvolumen · last) para `exclusiones.banda_opa`;
    el minuto es el del reloj monotónico (la ventana es relativa).
  * `suscripciones` aplica el tope sobre el conjunto DESEADO ordenado por
    prioridad; lo que no cabe se cuenta (`descartados_por_tope`) y sale en la
    foto. Tras una reconexión de DAS hay que llamar a `reiniciar_suscripciones`
    (las suscripciones no sobreviven al socket).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from app.bot_das.reglas.halts import TA_PARADO
from app.bot_das.reglas.precios import de_float
from app.bot_das.reloj import ET, hora_das_a_et
from app.bot_das.tipos import (
    COTIZACION_FRESCA_MAX_S,
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
FRESCA_MAX_S = COTIZACION_FRESCA_MAX_S  # §3.12 / D1-12: UNA constante (tipos) para `fresca`, `sin_cotizacion_desde` y la entrada
VELAS_MINUTO_MAX = 60                   # E1-08: velas de 1 min que se guardan por ticker (la banda de OPA mira 30)
# E1-06: cómo se clasificó el último halt de cada ticker (va a la foto; el decisor lo puede anotar)
CLASIF_UP = "up"                        # cuenta en k
CLASIF_UP_SIN_BANDAS = "up_sin_bandas"  # P en RTH sin las dos bandas: cuenta como UP (lo conservador para un corto)
CLASIF_DOWN = "down"
CLASIF_NO_CUENTA = "no_cuenta"          # fuera de RTH, H sin banda o por debajo de la tolerancia, Q
_CIEN = Decimal("100")
_DOS = Decimal("2")
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
        self._ta_halt: dict[str, str] = {}              # E1-02: TA con el que paró el último halt (P = LULD)
        self._clasif_halt: dict[str, str] = {}          # E1-06: clasificación del último halt (CLASIF_*)
        self._velas: dict[str, deque] = {}              # E1-08: [t_inicio_s, high, low, dólares] por minuto monotónico
        self._volumen_previo: dict[str, int] = {}

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
        last_nuevo: Optional[Decimal] = None
        for clave_cruda, valor in msg.campos.items():
            clave = str(clave_cruda).strip().lower()
            if clave in _CAMPOS_PRECIO:
                precio = _decimal_o_none(valor)
                if precio is None:
                    self._campos_ignorados += 1
                    continue
                setattr(cot, _CAMPOS_PRECIO[clave], precio if precio > 0 else None)
                if clave == "l" and precio > 0:
                    last_nuevo = precio
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
        self._vela(ticker, cot, last_nuevo, cot.actualizada_en)
        return ticker

    def _vela(self, ticker: str, cot: Cotizacion, last_nuevo: Optional[Decimal], mono: float) -> None:
        """E1-08: suma el `$Quote` a la vela de 1 min (minuto monotónico): high/low del `last`, dólares = Δvolumen · last."""
        volumen = cot.volumen
        previo = self._volumen_previo.get(ticker)
        if volumen is not None:
            self._volumen_previo[ticker] = volumen
        precio = last_nuevo if last_nuevo is not None else cot.last
        if precio is None or precio <= 0:
            return
        delta = volumen - previo if (volumen is not None and previo is not None and volumen > previo) else 0
        if last_nuevo is None and delta == 0:
            return                                   # ni print nuevo ni volumen: nada que sumar a la vela
        inicio = float(int(mono // 60) * 60)
        velas = self._velas.setdefault(ticker, deque(maxlen=VELAS_MINUTO_MAX))
        if velas and velas[-1][0] == inicio:
            vela = velas[-1]
            vela[1] = max(vela[1], precio)
            vela[2] = min(vela[2], precio)
            vela[3] += Decimal(delta) * precio
        else:
            velas.append([inicio, precio, precio, Decimal(delta) * precio])

    def velas_minuto(self, ticker: str) -> list[tuple[float, Decimal, Decimal, Decimal]]:
        """E1-08: [(t_inicio_s, high, low, dólares)] de las velas de 1 min del ticker, de la más vieja a la más nueva.

        Es la entrada de `exclusiones.banda_opa` (el tiempo es el monotónico:
        la banda solo mira la ventana relativa). Vacía si no hubo prints.
        """
        return [(v[0], v[1], v[2], v[3]) for v in self._velas.get(_norm(ticker), ())]

    def _aplicar_estado(self, simb: EstadoSimbolo, msg: MsgIssueStatus) -> None:
        if msg.ssr is not None:
            simb.ssr = msg.ssr
        simb.ta = _ta_normalizado(msg.ta)
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
        """Transición del símbolo con un `$IssueStatus`: «halt» (nuevo), «reapertura» (TA T/ausente tras un halt) o None.

        En un halt nuevo guarda `halt_desde` (TAT del mensaje si es válido, si
        no `ahora`), `precio_parada` (`last` o el último del libro), pone
        `orden_open_enviada = False` y suma k SOLO si el halt es UP y la franja
        es RTH (E1-06: `P` por cercanía a las bandas y, sin ellas, UP; `H` por
        la tolerancia bajo limit_up; `Q` no suma). En la reapertura borra
        `halt_desde` y la guardia; `precio_parada` se conserva para medir la
        subida (R-F-05) hasta el siguiente halt. E1-05: `Q` es PARADO (solo
        cotiza antes del cruce); H → Q no es transición. E1-10: el TA se
        compara normalizado.
        """
        simb = self.simbolo(ticker)
        self._aplicar_estado(simb, msg)
        ta = simb.ta or ""
        parado = ta in TA_PARADO
        if parado and simb.halt_desde is None:
            simb.halt_desde = self._inicio_halt(msg.tat, ahora)
            precio = last if last is not None else self._ultimo_precio(simb.ticker)
            simb.precio_parada = _precio_o_none(precio)
            simb.orden_open_enviada = False
            clasif = self._clasificar(ta, simb, franja)
            self._ta_halt[simb.ticker] = ta
            self._clasif_halt[simb.ticker] = clasif
            if clasif in (CLASIF_UP, CLASIF_UP_SIN_BANDAS):
                simb.k_halts_up += 1
            return "halt"
        if not parado and simb.halt_desde is not None:
            simb.halt_desde = None
            simb.orden_open_enviada = False
            return "reapertura"
        return None

    def _clasificar(self, ta: str, simb: EstadoSimbolo, franja: str) -> str:
        """E1-06: UP / UP sin bandas / DOWN / no cuenta para k (solo en RTH)."""
        if not str(franja).startswith("RTH") or ta not in ("H", "P"):
            return CLASIF_NO_CUENTA
        precio, up, down = simb.precio_parada, simb.limit_up, simb.limit_down
        if ta == "H":
            return CLASIF_UP if self._es_halt_up(precio, up) else CLASIF_NO_CUENTA
        if precio is None or up is None or down is None or up <= down:
            return CLASIF_UP_SIN_BANDAS
        return CLASIF_UP if precio >= (up + down) / _DOS else CLASIF_DOWN

    def ta_ultimo_halt(self, ticker: str) -> Optional[str]:
        """E1-02: el TA (normalizado) con el que paró el último halt del ticker; «P» = LULD. None si no paró hoy."""
        return self._ta_halt.get(_norm(ticker))

    def clasificacion_halt(self, ticker: str) -> Optional[str]:
        """E1-06: cómo se clasificó el último halt (CLASIF_UP, CLASIF_UP_SIN_BANDAS, CLASIF_DOWN o CLASIF_NO_CUENTA)."""
        return self._clasif_halt.get(_norm(ticker))

    def sembrar_k(self, ticker: str, k: int) -> int:
        """E1-03: repone k (halts UP del día) tras un reinicio o desde otra fuente; NUNCA lo baja. Devuelve el k vigente.

        ValueError si `k` no es un int ≥ 0 (un bool tampoco).
        """
        if type(k) is not int or k < 0:
            raise ValueError(f"k debe ser un int ≥ 0: {k!r}")
        simb = self.simbolo(ticker)
        if k > simb.k_halts_up:
            simb.k_halts_up = k
        return simb.k_halts_up

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
                "ta_ultimo_halt": self._ta_halt.get(ticker),
                "clasificacion": self._clasif_halt.get(ticker),
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


def _ta_normalizado(ta: object) -> Optional[str]:
    """E1-10: TA sin espacios y en mayúsculas; vacío o ausente → None (sin TA = normal)."""
    if ta is None:
        return None
    texto = str(ta).strip().upper()
    return texto or None


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
