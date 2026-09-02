"""Estado del mercado entero, acumulado desde el WebSocket.

Es lo que permite al radar preguntar «¿este ticker cumple el filtro de universo
de la estrategia?» sin pedir nada por REST: los datos ya vienen llegando.

POR QUE ACUMULAR Y NO MIRAR EL PRECIO DE AHORA. `PM High Gap %` —la condicion de
1B— es el MAXIMO de premercado contra el cierre de ayer, y un maximo no baja.
Un ticker que a las 05:00 hizo +80 % y a las 06:00 esta en +22 % SIGUE
cumpliendo: su maximo sigue siendo 80. Filtrar por el precio del momento lo
descartaria justo cuando la estrategia lo querria — y en gaps en corto,
retroceder tras el maximo es lo normal, no la excepcion.

Es el mismo calculo que hace el motor (`indicators._pm_running_series` con
`fmax.accumulate`), de modo que el radar y la estrategia coinciden por
construccion en vez de por parecido.

El planteamiento esta copiado de `live_screener_service`, que lleva haciendo
esto en produccion: mismo acumulado de `pre_high`, misma base `prevDay.c`.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("btt.bot_alerts.mercado")

ET = ZoneInfo("America/New_York")

# Minutos desde medianoche, hora de Nueva York.
PRE_INICIO = 4 * 60          # 04:00
RTH_INICIO = 9 * 60 + 30     # 09:30
RTH_FIN = 16 * 60            # 16:00


def sesion_de(minutos: int) -> str:
    if PRE_INICIO <= minutos < RTH_INICIO:
        return "premarket"
    if RTH_INICIO <= minutos < RTH_FIN:
        return "regular"
    return "cerrado"


@dataclass
class EstadoTicker:
    """Lo que se sabe de un ticker hoy. Todo acumulado desde el socket."""
    ticker: str
    prev_close: Optional[float] = None      # del snapshot: cierre RTH de AYER
    precio: Optional[float] = None          # ultimo visto
    pre_high: Optional[float] = None        # maximo de premercado ACUMULADO
    pre_low: Optional[float] = None
    pre_volume: float = 0.0
    rth_open: Optional[float] = None        # primera vela de la sesion regular
    rth_high: Optional[float] = None
    day_volume: float = 0.0
    visto_at: float = 0.0

    # ── metricas, con los mismos nombres que los filtros de universo ──────
    def metricas(self) -> dict:
        """Lo que el radar compara contra las reglas de cada estrategia.

        Un valor a None significa «hoy todavia no se puede saber», y el radar
        lo trata como NO cumple — nunca como cero. Es la diferencia entre «el
        gap de apertura es 0 %» y «aun no ha abierto», que decidiria distinto.
        """
        pc = self.prev_close
        def gap(v):
            if pc is None or pc <= 0 or v is None:
                return None
            return (v - pc) / pc * 100.0

        return {
            # Maximo de premercado vs cierre de ayer. ACUMULADO: no baja.
            "PM High Gap %": gap(self.pre_high),
            # Donde esta el precio AHORA. Este si sube y baja.
            "Current Gap %": gap(self.precio),
            # Apertura de la sesion regular vs cierre de ayer. None hasta 09:30
            # — no existe antes, y por eso 2.1B y 3B no son vigilables en
            # premercado.
            "Open Gap %": gap(self.rth_open),
            "Premarket Volume": self.pre_volume,
            "Volume": self.day_volume,
            "Price": self.precio,
            "Previous Close": pc,
        }


class MercadoEnVivo:
    """El mercado entero, actualizado con cada mensaje del socket."""

    def __init__(self):
        self._estados: dict[str, EstadoTicker] = {}
        self._lock = threading.Lock()
        self.mensajes = 0
        self._dia: Optional[str] = None

    # ── base: el cierre de ayer, del snapshot ────────────────────────────
    def sembrar_prev_close(self, datos: dict[str, float]) -> int:
        """Cierres de ayer de todo el mercado, de una foto REST.

        Hace falta porque el socket NO lo trae: los agregados hablan del dia de
        hoy. Sin esta base no hay gap que calcular.
        """
        with self._lock:
            for tk, pc in datos.items():
                st = self._estados.get(tk)
                if st is None:
                    st = EstadoTicker(ticker=tk)
                    self._estados[tk] = st
                st.prev_close = pc
        return len(datos)

    def sembrar_maximos(self, ticker: str, velas: list[dict]) -> None:
        """Rellena el maximo de premercado de un ticker con sus velas de HOY.

        SIN ESTO, CADA REINICIO CIEGA AL BOT. El maximo se acumula desde que el
        proceso arranca, asi que un ticker que hizo su gap antes queda invisible
        para siempre — y el filtro de universo es justo un maximo.

        Medido el 2026-09-02: GELS habia hecho maximo 0,80 sobre un cierre de
        0,532 (PM High Gap 50,4 %, cumple 1B) y estaba en 0,65 (+22 %). Tras
        reiniciar el bot, el radar dejo de verlo: solo veia el 22 % de ahora.

        `velas` son las que devuelve `hidratar_rest` (columnas del motor).
        """
        if not velas:
            return
        with self._lock:
            st = self._estados.get(ticker)
            if st is None:
                st = EstadoTicker(ticker=ticker)
                self._estados[ticker] = st
            for v in velas:
                ts = v.get("timestamp")
                if ts is None:
                    continue
                minutos = ts.hour * 60 + ts.minute
                ses = sesion_de(minutos)
                hi, lo = v.get("high"), v.get("low")
                if ses == "premarket":
                    st.pre_volume += float(v.get("volume") or 0.0)
                    if hi is not None:
                        st.pre_high = float(hi) if st.pre_high is None else max(st.pre_high, float(hi))
                    if lo is not None:
                        st.pre_low = float(lo) if st.pre_low is None else min(st.pre_low, float(lo))
                elif ses == "regular":
                    if st.rth_open is None:
                        st.rth_open = float(v.get("open") or v.get("close") or 0.0)
                    if hi is not None:
                        st.rth_high = float(hi) if st.rth_high is None else max(st.rth_high, float(hi))
            ultima = velas[-1]
            if ultima.get("close") is not None:
                st.precio = float(ultima["close"])

    def reiniciar_si_cambia_el_dia(self, ahora: Optional[datetime] = None) -> bool:
        """Un dia nuevo empieza en blanco: el maximo de premercado de ayer no
        vale para hoy. Devuelve True si se reinicio."""
        hoy = (ahora or datetime.now(tz=ET)).strftime("%Y-%m-%d")
        if self._dia == hoy:
            return False
        with self._lock:
            for st in self._estados.values():
                st.pre_high = st.pre_low = st.rth_open = st.rth_high = None
                st.pre_volume = st.day_volume = 0.0
                st.precio = None
            self._dia = hoy
        logger.info("[MERCADO] dia nuevo (%s): acumulados a cero", hoy)
        return True

    # ── el socket ────────────────────────────────────────────────────────
    def aplicar(self, ev: dict) -> None:
        """Un agregado por segundo (`A`) o por minuto (`AM`)."""
        tk = ev.get("sym")
        ts = ev.get("s") or ev.get("t")
        if not tk or ts is None:
            return
        hi, lo, cl = ev.get("h"), ev.get("l"), ev.get("c")
        vol = float(ev.get("v") or 0.0)
        if cl is None:
            return

        t = datetime.fromtimestamp(int(ts) / 1000, tz=ET)
        minutos = t.hour * 60 + t.minute
        ses = sesion_de(minutos)

        with self._lock:
            self.mensajes += 1
            st = self._estados.get(tk)
            if st is None:
                st = EstadoTicker(ticker=tk)
                self._estados[tk] = st

            st.precio = float(cl)
            st.visto_at = t.timestamp()
            # `av` es el volumen acumulado del dia y viene ya oficial; sumar los
            # `v` deja fuera operaciones (medido: hasta un 4,6 % menos).
            av = ev.get("av")
            if av is not None:
                st.day_volume = float(av)
            else:
                st.day_volume += vol

            if ses == "premarket":
                st.pre_volume += vol
                if hi is not None:
                    h = float(hi)
                    st.pre_high = h if st.pre_high is None else max(st.pre_high, h)
                if lo is not None:
                    l = float(lo)
                    st.pre_low = l if st.pre_low is None else min(st.pre_low, l)
            elif ses == "regular":
                if st.rth_open is None:
                    st.rth_open = float(ev.get("o") or cl)
                if hi is not None:
                    h = float(hi)
                    st.rth_high = h if st.rth_high is None else max(st.rth_high, h)

    # ── consulta ─────────────────────────────────────────────────────────
    def estado(self, ticker: str) -> Optional[EstadoTicker]:
        with self._lock:
            return self._estados.get(ticker)

    def todos(self) -> list[EstadoTicker]:
        with self._lock:
            return list(self._estados.values())

    @property
    def tickers_con_datos(self) -> int:
        with self._lock:
            return sum(1 for s in self._estados.values() if s.precio is not None)
