"""Barras de 1 minuto en vivo y sus derivados, por ticker y sesión.

Se alimentan de los agregados por SEGUNDO (`A.*`) que el live screener ya está
recibiendo: no abrimos una segunda conexión a Massive (la cuenta admite una sola
por clase de activo, y el propio consumidor del screener ya sufre el kick-loop
1008 cuando hay dos). Agregando nosotros los segundos tenemos la barra cerrada en
el segundo :00 en vez de esperar a que Massive publique el `AM`.

Anclaje: la serie arranca a las 04:00 ET. Es deliberado — el VWAP es acumulado
desde la primera barra del frame, así que empezar a las 6:00 daría un VWAP que no
es el de nadie. Los minutos sin operaciones NO se rellenan: Massive no emite barra
si no hubo trades, y el lake tampoco los rellena.

Todo el estado es incremental (sumas acumuladas, EMA recursiva, máximo corrido).
No se guardan arrays del día ni se recalcula nada al cerrar cada barra.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PM_OPEN_MIN = 4 * 60      # 04:00 ET — ancla de la serie
SESSION_END_MIN = 20 * 60  # 20:00 ET — fin de after-hours
RTH_OPEN_MIN = 9 * 60 + 30

EMA_PERIODS = (9, 15, 20, 50, 200)
SMA_PERIODS = (20, 50)

# El offset ET cambia dos veces al año; calcularlo por mensaje sería carísimo con
# el firehose de `A.*`. Se cachea por fecha UTC.
_offset_cache: Tuple[Optional[str], int] = (None, 0)


def et_minute_of_day(ts_ms: int) -> int:
    """Minuto del día en hora de Nueva York (0-1439) para un epoch en ms."""
    global _offset_cache
    secs = ts_ms // 1000
    day_key = str(secs // 86400)
    cached_key, cached_off = _offset_cache
    if cached_key != day_key:
        dt = datetime.fromtimestamp(secs, tz=timezone.utc).astimezone(ET)
        cached_off = int(dt.utcoffset().total_seconds()) if dt.utcoffset() else 0
        _offset_cache = (day_key, cached_off)
    return int(((secs + cached_off) // 60) % 1440)


def et_date_key(ts_ms: int) -> str:
    """Fecha de sesión ET (YYYY-MM-DD) de un epoch en ms."""
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).astimezone(ET).strftime("%Y-%m-%d")


class _Rolling:
    """Media móvil simple sobre una ventana pequeña, sin numpy ni deque de objetos."""

    __slots__ = ("period", "buf", "idx", "count", "total")

    def __init__(self, period: int):
        self.period = period
        self.buf = [0.0] * period
        self.idx = 0
        self.count = 0
        self.total = 0.0

    def push(self, v: float) -> Optional[float]:
        if self.count == self.period:
            self.total -= self.buf[self.idx]
        else:
            self.count += 1
        self.buf[self.idx] = v
        self.total += v
        self.idx = (self.idx + 1) % self.period
        return (self.total / self.count) if self.count == self.period else None


class SessionBars:
    """Serie de 1 minuto de UN ticker en UNA sesión, con derivados incrementales."""

    __slots__ = (
        "ticker", "session_date",
        "_cur_min", "_o", "_h", "_l", "_c", "_v",
        "bar_count", "last_bar", "prev_bar",
        "cum_tp_vol", "cum_vol",
        "pm_high", "pm_low",
        "session_max", "session_min", "max_at_min",
        "_ema", "_sma",
        "last_close_min",
        "_prev_derived",
    )

    def __init__(self, ticker: str, session_date: str):
        self.ticker = ticker
        self.session_date = session_date
        self._cur_min: Optional[int] = None
        self._o = self._h = self._l = self._c = 0.0
        self._v = 0.0
        self.bar_count = 0
        self.last_bar: Optional[Dict[str, float]] = None
        self.prev_bar: Optional[Dict[str, float]] = None
        self.cum_tp_vol = 0.0
        self.cum_vol = 0.0
        self.pm_high: Optional[float] = None
        self.pm_low: Optional[float] = None
        self.session_max: Optional[float] = None
        self.session_min: Optional[float] = None
        self.max_at_min: Optional[int] = None
        self._ema: Dict[int, Optional[float]] = {p: None for p in EMA_PERIODS}
        self._sma: Dict[int, _Rolling] = {p: _Rolling(p) for p in SMA_PERIODS}
        self.last_close_min: Optional[int] = None
        # Snapshot derivado (VWAP, EMA, extremos…) tal como quedó al cierre de la
        # barra ANTERIOR. Es lo que hace posible «cierre cruza el VWAP»: el cruce
        # necesita el valor previo de AMBOS lados, y el del VWAP/EMA no está en la
        # barra cruda. Sin esto, un cruce contra un campo derivado no salta nunca.
        self._prev_derived: Dict[str, Optional[float]] = {}

    # ── ingesta ──────────────────────────────────────────────────────────────
    def ingest(self, ts_ms: int, o: Optional[float], h: Optional[float],
               l: Optional[float], c: Optional[float], v: Optional[float]) -> Optional[Dict[str, float]]:
        """Acumula un agregado de segundo. Devuelve la barra de 1m si ese
        agregado ha cerrado la anterior; None en caso contrario."""
        minute = et_minute_of_day(ts_ms)
        if minute < PM_OPEN_MIN or minute >= SESSION_END_MIN:
            return None  # fuera de sesión: no forma parte de la serie anclada a las 4:00
        price = c if c is not None else o
        if price is None or not math.isfinite(price):
            return None
        hi = h if h is not None else price
        lo = l if l is not None else price
        vol = v if (v is not None and math.isfinite(v)) else 0.0

        closed: Optional[Dict[str, float]] = None
        if self._cur_min is None:
            self._start(minute, o if o is not None else price, hi, lo, price, vol)
            return None
        if minute != self._cur_min:
            closed = self._finalize()
            self._start(minute, o if o is not None else price, hi, lo, price, vol)
            return closed
        # mismo minuto: acumular
        self._h = max(self._h, hi)
        self._l = min(self._l, lo)
        self._c = price
        self._v += vol
        return None

    def _start(self, minute: int, o: float, h: float, l: float, c: float, v: float) -> None:
        self._cur_min = minute
        self._o, self._h, self._l, self._c, self._v = o, h, l, c, v

    def close_stale(self, now_minute: int) -> Optional[Dict[str, float]]:
        """Cierra la barra en curso si el reloj ya pasó de su minuto.

        Un ticker que deja de operar no volvería a mandar un agregado, y sin esto
        su última barra se quedaría abierta indefinidamente y la alarma no se
        evaluaría nunca sobre ella."""
        if self._cur_min is None or now_minute <= self._cur_min:
            return None
        return self._finalize()

    def _finalize(self) -> Dict[str, float]:
        # ANTES de incorporar esta barra, snapshot() aún refleja la barra previa
        # (mismo estado acumulado, mismo last_bar): se guarda como «valores de la
        # barra anterior» para los operadores de cruce. En la primera barra no hay
        # previa y queda {} (un cruce no dispara, que es lo correcto).
        self._prev_derived = self.snapshot() if self.last_bar is not None else {}

        minute = int(self._cur_min or 0)
        o, h, l, c, v = self._o, self._h, self._l, self._c, self._v
        self._cur_min = None

        # VWAP acumulado desde las 04:00 (precio típico ponderado por volumen).
        typical = (h + l + c) / 3.0
        self.cum_tp_vol += typical * v
        self.cum_vol += v

        if minute < RTH_OPEN_MIN:
            self.pm_high = h if self.pm_high is None else max(self.pm_high, h)
            self.pm_low = l if self.pm_low is None else min(self.pm_low, l)

        # Máximo/mínimo corridos de la sesión. `max_at_min` guarda cuándo se hizo
        # el último máximo: es lo que alimenta `mins_since_high`.
        if self.session_max is None or h > self.session_max:
            self.session_max = h
            self.max_at_min = minute
        if self.session_min is None or l < self.session_min:
            self.session_min = l

        for p in EMA_PERIODS:
            prev = self._ema[p]
            k = 2.0 / (p + 1.0)
            self._ema[p] = c if prev is None else (c - prev) * k + prev
        for p in SMA_PERIODS:
            self._sma[p].push(c)

        self.prev_bar = self.last_bar
        bar = {"minute": minute, "open": o, "high": h, "low": l, "close": c, "volume": v}
        self.last_bar = bar
        self.bar_count += 1
        self.last_close_min = minute
        return bar

    # ── derivados ────────────────────────────────────────────────────────────
    def vwap(self) -> Optional[float]:
        return (self.cum_tp_vol / self.cum_vol) if self.cum_vol > 0 else None

    def snapshot(self) -> Dict[str, Optional[float]]:
        """Valores de los campos BAR referidos a la ÚLTIMA barra cerrada.

        Devuelve None en los campos que aún no tienen valor (EMA sin suficientes
        barras, VWAP sin volumen). El evaluador trata None como «la condición no
        se cumple», nunca como cero — un 0 silencioso dispararía alarmas falsas."""
        b = self.last_bar
        if b is None:
            return {}
        pb = self.prev_bar or {}
        vw = self.vwap()
        close = b["close"]
        out: Dict[str, Optional[float]] = {
            "close": close,
            "open": b["open"],
            "high": b["high"],
            "low": b["low"],
            "bar_volume": b["volume"],
            "dollar_volume": close * b["volume"],
            "prev_bar_close": pb.get("close"),
            "prev_bar_high": pb.get("high"),
            "prev_bar_low": pb.get("low"),
            "vwap": vw,
            "dist_vwap_pct": ((close / vw - 1.0) * 100.0) if (vw and vw > 0) else None,
            "pm_high": self.pm_high,
            "pm_low": self.pm_low,
            "previous_max": self.session_max,
            "previous_min": self.session_min,
            "mins_since_high": (b["minute"] - self.max_at_min) if self.max_at_min is not None else None,
        }
        for p in EMA_PERIODS:
            out[f"ema{p}"] = self._ema[p]
        for p in SMA_PERIODS:
            out[f"sma{p}"] = self._sma[p].total / self._sma[p].count if self._sma[p].count == p else None
        return out

    def prev_snapshot_value(self, key: str) -> Optional[float]:
        """Valor de un campo en la barra ANTERIOR, para los operadores de cruce.

        Cubre TODOS los campos derivados (VWAP, EMA, SMA, extremos corridos,
        distancia al VWAP…), no solo el precio crudo: `_prev_derived` es el
        snapshot completo tal como quedó al cierre de la barra previa. Así
        «cierre cruza el VWAP» funciona; antes solo había close/open/high/low y
        un cruce contra un derivado no saltaba nunca."""
        return self._prev_derived.get(key)


class BarStore:
    """Series de barras vivas, indexadas por ticker. Se purga al cambiar de día."""

    def __init__(self) -> None:
        self._series: Dict[str, SessionBars] = {}
        self._date: Optional[str] = None

    def get(self, ticker: str, session_date: str) -> SessionBars:
        if self._date != session_date:
            self._series.clear()
            self._date = session_date
        s = self._series.get(ticker)
        if s is None:
            s = SessionBars(ticker, session_date)
            self._series[ticker] = s
        return s

    def peek(self, ticker: str) -> Optional[SessionBars]:
        return self._series.get(ticker)

    def tickers(self):
        return list(self._series.keys())

    def drop(self, ticker: str) -> None:
        self._series.pop(ticker, None)

    def __len__(self) -> int:
        return len(self._series)
