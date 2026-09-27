"""Hora ET, reloj simulado para replay, desvío SNTP y veredicto.

QUÉ HACE. `Reloj` es la única fuente de `datetime` del bot (riesgo 13): hora
ET aware, monotónico para latencias y plazos, epoch para el latido.
`RelojSimulado` se avanza a mano (tests y replay, R-O-02). `desvio_sntp`
pregunta a un servidor de hora por UDP con la stdlib y `veredicto_reloj`
aplica R-J-07: más de 2 s el bot se NIEGA a operar; más de 0,5 s, aviso.

POR QUÉ ESTÁ AQUÍ. La memoria del proyecto dice que el reloj del PC deriva
~0,6 s/día y llegó a 2,5 s: una caducidad de señal (R-B-04) o una latencia
medida con un reloj torcido miente sin dar error. Por eso las latencias se
miden con `mono()` y la hora de pared se contrasta al arrancar y cada hora.

LAS TRAMPAS.
  * `%ORDER` trae `HH:MM:SS` sin fecha (riesgo 10): `hora_das_a_et` lo
    combina con `hoy` del reloj, nunca con la fecha local del VPS.
  * Y SIN zona (L0-05): DAS Trader pinta las horas en la zona que tenga
    configurada. `hora_das_a_et` supone ET, y nadie lo ha verificado contra
    el DAS real; si el DAS del VPS estuviera en hora de Madrid, el TAT de un
    halt y las horas de los fills vendrían 6 h desplazados. El paso canario
    de `comprobar_das` debe comparar la hora de un `%ORDER` recién enviado
    con `ahora()` usando `hora_das_es_et` (tolerancia 60 s) y abortar si no
    casa.
  * `RelojSimulado.mono()` avanza EXACTAMENTE lo que se avanza la hora, y
    nunca retrocede aunque `fijar` vaya hacia atrás: monotónico es monotónico.
    Arranca en 1 000,0 para que ningún «0.0 = sin valor» del estado coincida
    con un instante real.
  * `desvio_sntp` NUNCA lanza y NUNCA se llama al importar; devuelve `None`
    si no hay respuesta (timeout, DNS, puerto cerrado, paquete corto o
    «kiss-o'-death» con stratum 0). El signo: positivo = el reloj local va
    ATRASADO respecto al servidor; negativo = adelantado (el caso de la memoria).
  * Las horas «HH:MM» de la config y del libro se interpretan en ET con
    `zoneinfo` (horario de verano incluido, L3): nunca `datetime(..., tzinfo=
    pytz)` ni hora local del sistema.
"""
from __future__ import annotations

import socket
import struct
import time
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.bot_das.tipos import RELOJ_AVISO_S, RELOJ_NEGARSE_S

ET = ZoneInfo("America/New_York")
_MONO_INICIAL_SIMULADO = 1_000.0
_NTP_DELTA = 2_208_988_800          # segundos entre 1900-01-01 y 1970-01-01
_SNTP_PUERTO = 123
_SNTP_PETICION = b"\x1b" + 47 * b"\0"   # LI=0, VN=3, Mode=3 (cliente); 48 bytes
DESFASE_HORA_DAS_MAX_S = 60.0       # L0-05: más que esto entre la hora de un %ORDER recién enviado y ET → DAS no está en ET


class Reloj:
    """Reloj real: hora ET aware, monotónico y epoch del sistema."""

    def ahora(self) -> datetime:
        """Aware, ET."""
        return datetime.now(tz=ET)

    def mono(self) -> float:
        """`time.monotonic()`: para latencias y plazos, inmune a saltos del reloj de pared."""
        return time.monotonic()

    def hoy(self) -> date:
        return self.ahora().date()

    def epoch(self) -> float:
        """Segundos desde 1970 del instante `ahora()` (para el latido por fichero)."""
        return self.ahora().timestamp()


class RelojSimulado(Reloj):
    """Reloj que solo avanza cuando se le dice (tests, replay R-O-02).

    `inicio` naive se toma como hora ET; aware se convierte a ET.
    """

    def __init__(self, inicio: datetime) -> None:
        self._actual = _a_et(inicio)
        self._mono = _MONO_INICIAL_SIMULADO

    def ahora(self) -> datetime:
        return self._actual

    def mono(self) -> float:
        return self._mono

    def avanzar(self, s: float) -> None:
        """Adelanta la hora y el monotónico `s` segundos (s ≥ 0)."""
        if s < 0:
            raise ValueError(f"no se puede avanzar un tiempo negativo: {s}")
        self._actual = self._actual + timedelta(seconds=s)
        self._mono += s

    def fijar(self, dt: datetime) -> None:
        """Pone la hora en `dt`; el monotónico avanza la diferencia si es positiva y NUNCA retrocede."""
        nuevo = _a_et(dt)
        delta = (nuevo - self._actual).total_seconds()
        self._actual = nuevo
        if delta > 0:
            self._mono += delta


def _a_et(dt: datetime) -> datetime:
    """Naive → se asume ET; aware → se convierte a ET."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def desvio_sntp(servidor: str = "time.windows.com", timeout_s: float = 3.0,
                puerto: int = _SNTP_PUERTO) -> Optional[float]:
    """Desvío del reloj local respecto a `servidor` en segundos (R-J-07), o None si no contesta.

    SNTP (RFC 4330) con un socket UDP de la stdlib: desvío = ((t2 − t1) +
    (t3 − t4)) / 2 con t1/t4 locales (envío/recepción) y t2/t3 del servidor
    (recepción/transmisión). Positivo = el reloj local va atrasado. NUNCA
    lanza: cualquier fallo de red o de formato es «no se pudo preguntar».
    `puerto` existe para que los tests apunten a un servidor UDP local.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout_s)
            t1 = time.time()
            sock.sendto(_SNTP_PETICION, (servidor, puerto))
            datos, _ = sock.recvfrom(1024)
            t4 = time.time()
    except (OSError, ValueError, OverflowError):   # frontera de red: timeout, DNS, puerto cerrado, host inválido → None (R-J-07 «sin SNTP» = aviso, no error)
        return None
    if len(datos) < 48:
        return None
    palabras = struct.unpack("!12I", datos[:48])
    stratum = (palabras[0] >> 16) & 0xFF
    if stratum == 0:                                   # kiss-o'-death / servidor sin sincronizar
        return None
    t2 = _ntp_a_epoch(palabras[8], palabras[9])
    t3 = _ntp_a_epoch(palabras[10], palabras[11])
    if t3 == 0.0 or t2 == 0.0:
        return None
    return ((t2 - t1) + (t3 - t4)) / 2.0


def _ntp_a_epoch(segundos: int, fraccion: int) -> float:
    """Marca NTP (segundos desde 1900 + fracción de 2^32) → epoch Unix; 0.0 si está vacía."""
    if segundos == 0 and fraccion == 0:
        return 0.0
    return segundos - _NTP_DELTA + fraccion / 2**32


def veredicto_reloj(desvio: Optional[float], negarse_s: float = RELOJ_NEGARSE_S,
                    aviso_s: float = RELOJ_AVISO_S) -> tuple[bool, Optional[str]]:
    """(puede_operar, aviso) según R-J-07: > 2 s se niega; > 0,5 s avisa; None → (True, "sin SNTP").

    Los umbrales son estrictos («más de»): 2,0 s exactos solo avisa y 0,5 s
    exactos no dice nada. Se mira el valor absoluto: adelantado o atrasado da
    igual para la caducidad de una señal.
    """
    if desvio is None:
        return True, "sin SNTP"
    magnitud = abs(desvio)
    if magnitud > negarse_s:
        return False, (f"reloj desviado {desvio:+.2f} s (más de {negarse_s:g} s): "
                       f"el bot se NIEGA a operar (R-J-07)")
    if magnitud > aviso_s:
        return True, f"reloj desviado {desvio:+.2f} s (más de {aviso_s:g} s): aviso (R-J-07)"
    return True, None


def a_hora_et(hhmm: str, dia: date) -> datetime:
    """«HH:MM» (config, libro) → datetime aware ET del día `dia`. Lanza ValueError si está mal formada."""
    horas, minutos = _partir_hora(hhmm, 2)
    return datetime(dia.year, dia.month, dia.day, horas, minutos, tzinfo=ET)


def hora_das_a_et(hhmmss: str, hoy: date) -> datetime:
    """«HH:MM:SS» de `%ORDER`/`%OrderAct`/`%TRADE` (sin fecha) → datetime aware ET del día `hoy` (riesgo 10).

    Da por hecho que DAS emite en ET (L0-05: NO verificado; depende de la
    zona configurada en DAS Trader). `desfase_hora_das_s` / `hora_das_es_et`
    permiten comprobarlo con un `%ORDER` recién enviado (paso canario de
    `comprobar_das`) antes de fiarse de las horas de halts y fills.
    """
    horas, minutos, segundos = _partir_hora(hhmmss, 3)
    return datetime(hoy.year, hoy.month, hoy.day, horas, minutos, segundos, tzinfo=ET)


def desfase_hora_das_s(hhmmss: str, ahora: datetime) -> float:
    """Segundos (con signo) entre la hora «HH:MM:SS» de una línea de DAS recién recibida y `ahora` en ET (L0-05).

    Positivo = DAS va por delante de ET. Se lleva al intervalo [−12 h, +12 h)
    para que una línea emitida justo antes de medianoche no parezca un
    desfase de 24 h. `ahora` aware (se convierte a ET) o naive (se toma
    como ET). Lanza ValueError con una hora mal formada.
    """
    horas, minutos, segundos = _partir_hora(hhmmss, 3)
    if ahora.tzinfo is not None and ahora.utcoffset() is not None:
        ahora = ahora.astimezone(ET)
    das = horas * 3600 + minutos * 60 + segundos
    local = ahora.hour * 3600 + ahora.minute * 60 + ahora.second + ahora.microsecond / 1_000_000
    medio_dia = 12 * 3600
    return ((das - local + medio_dia) % (24 * 3600)) - medio_dia


def hora_das_es_et(hhmmss: str, ahora: datetime, tolerancia_s: float = DESFASE_HORA_DAS_MAX_S) -> bool:
    """True si la hora de DAS casa con `ahora` ET dentro de `tolerancia_s` (60 s): DAS está configurado en ET (L0-05)."""
    return abs(desfase_hora_das_s(hhmmss, ahora)) <= tolerancia_s


def _partir_hora(texto: str, partes: int) -> tuple[int, ...]:
    """«HH:MM» o «HH:MM:SS» → enteros validados; ValueError con texto claro si no cuadra."""
    if not isinstance(texto, str):
        raise ValueError(f"hora debe ser texto, no {texto!r}")
    trozos = texto.strip().split(":")
    if len(trozos) != partes or not all(t.isdigit() and len(t) == 2 for t in trozos):
        raise ValueError(f"hora mal formada: {texto!r} (se esperaba {'HH:MM' if partes == 2 else 'HH:MM:SS'})")
    valores = tuple(int(t) for t in trozos)
    topes = (23, 59, 59)
    for valor, tope in zip(valores, topes):
        if valor > tope:
            raise ValueError(f"hora fuera de rango: {texto!r}")
    return valores
