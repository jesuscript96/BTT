"""
Profiler fino de sub-fases del bucle `stream_build` (PRD_PERF_BACKTEST_STREAMBUILD_20260827 §7).

**Apagado por defecto** (regla R7 del repo): poner `BACKTEST_PROFILE_SUBPHASES=1`
al arrancar el backend para activarlo. Con la variable apagada todos los puntos de
instrumentación son un chequeo de booleano y no cambian NADA del motor.

Solo MIDE (perf_counter + acumuladores en memoria); no toca datos, ni flujo, ni
resultados. Cubre el camino SECUENCIAL de `run_backtest` (el que corre por
defecto sin BTT_SLAB_STREAM_ENABLED / BACKTEST_PARALLEL_WORKERS): en modo slab o
paralelo los `mark()` no se llegan a llamar y el reporte sale casi vacío.

Sub-fases del bucle (backtest_service.run_backtest):
  fetch     — next() del iterador de ticker-días (I/O del stream + descompresión)
  prep      — exclusiones, orden, estructura de mercado (HOD/LOD/PM) y mini_df
  translate — translate_strategy() completo, señales de entrada/salida
  postproc  — recorte de sesión, candle_delay, parseo de riesgo, kwargs de sim
  simulate  — kernel Numba simulate()
  emit      — enriquecido de trades, equity y stats del día

Dentro de translate_strategy (path legacy pandas, strategy_engine/indicators):
  resample   — _resample_if_needed (pandas resample 1m→Nm)          [anidado en translate]
  indicators — compute_indicator (EMAs, ATR, volumen acumulado...)   [anidado en translate]
  align      — _align_signals_to_1m (baja señales Nm→1m)             [anidado en translate]

La suma fetch+prep+translate+postproc+simulate+emit no tiene que cuadrar al 100 %
con la fase `stream_build` de perf_timing: esa fase también incluye prefetch y
montaje previo al bucle. El reporte muestra la diferencia como `unaccounted`.
"""
import logging
import os
import time

logger = logging.getLogger("backtester.subphase")

ENABLED = os.getenv("BACKTEST_PROFILE_SUBPHASES", "").strip().lower() in ("1", "true", "yes", "on")

# Fases del bucle, en orden de aparición. Las tres últimas son sub-fases
# anidadas dentro de `translate` (se listan aparte para el desglose fino).
LOOP_PHASES = ("fetch", "prep", "translate", "postproc", "simulate", "emit")
NESTED_PHASES = ("resample", "indicators", "align")


class SubPhaseProfiler:
    """Acumulador global de tiempos por sub-fase. Instancia única `PROF`."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._acc: dict[str, float] = {}      # fase -> segundos acumulados
        self._counts: dict[str, int] = {}     # fase -> nº de llamadas
        self._open: str | None = None         # segmento abierto por mark()
        self._t_open: float = 0.0
        self._snap: tuple | None = None       # (ticker, date, copia de _acc) del día en curso

    # ── API de acumulación ────────────────────────────────────────────────

    def acc(self, phase: str, seconds: float) -> None:
        self._acc[phase] = self._acc.get(phase, 0.0) + seconds
        self._counts[phase] = self._counts.get(phase, 0) + 1

    def mark(self, phase: str) -> None:
        """Cierra el segmento abierto y abre `phase`.

        Los `continue` del bucle no pasan por ningún mark: el tiempo hasta el
        siguiente mark/day_boundary queda atribuido al segmento que estaba
        abierto, que es justamente la fase en la que el día se descartó.
        """
        now = time.perf_counter()
        if self._open is not None:
            self.acc(self._open, now - self._t_open)
        self._open = phase
        self._t_open = now

    def timed_iter(self, it):
        """Envuelve el iterador de ticker-días: cada next() cuenta como `fetch`.

        El tiempo ENTRE yields (el cuerpo del bucle) nunca cae aquí: el cronómetro
        solo corre alrededor de next(), así el I/O del stream queda separado del
        cómputo aunque el for sea quien pide el siguiente elemento.
        """
        while True:
            t0 = time.perf_counter()
            try:
                item = next(it)
            except StopIteration:
                break
            self.acc("fetch", time.perf_counter() - t0)
            yield item

    def day_boundary(self, ticker: str, date: str) -> None:
        """Arranque de un ticker-día: cierra segmentos y vuelca el día anterior."""
        now = time.perf_counter()
        if self._open is not None:
            self.acc(self._open, now - self._t_open)
            self._open = None
        if self._snap is not None:
            self._log_day(self._snap, now)
        self._snap = (ticker, date, dict(self._acc))

    def _log_day(self, snap: tuple, now: float) -> None:
        ptk, pdate, pacc = snap
        delta = {}
        for k, v in self._acc.items():
            dv = v - pacc.get(k, 0.0)
            if dv > 1e-6:
                delta[k] = dv * 1000.0
        tot = sum(delta.values())
        if tot <= 0:
            return
        parts = " ".join(f"{k}={v:.1f}ms" for k, v in sorted(delta.items()))
        logger.info("[SUBPHASE-DAY] %s %s total=%.1fms %s", ptk, pdate, tot, parts)

    # ── Reporte ───────────────────────────────────────────────────────────

    def report(self, stream_build_ms: float, loop_ms: float, n_days: int) -> None:
        """Vuelca el desglose agregado. Referencias: fase stream_build de
        perf_timing (todo run_backtest) y loop_ms (solo el bucle, desde t1)."""
        now = time.perf_counter()
        if self._open is not None:
            self.acc(self._open, now - self._t_open)
            self._open = None
        if self._snap is not None:
            self._log_day(self._snap, now)
            self._snap = None

        loop_total = sum(self._acc.get(p, 0.0) for p in LOOP_PHASES) * 1000.0
        nested_total = sum(self._acc.get(p, 0.0) for p in NESTED_PHASES) * 1000.0
        logger.info(
            "[SUBPHASE-SUMMARY] days=%s loop=%.0fms stream_build=%.0fms "
            "medido_bucle=%.0fms (de las cuales translate anidado: %.0fms)",
            n_days, loop_ms, stream_build_ms, loop_total, nested_total,
        )
        for phase in LOOP_PHASES + NESTED_PHASES:
            s = self._acc.get(phase)
            if not s:
                continue
            ms = s * 1000.0
            n = self._counts.get(phase, 0)
            logger.info(
                "[SUBPHASE] phase=%s ms=%.1f pct_stream_build=%.1f%% pct_loop=%.1f%% calls=%d",
                phase, ms,
                100.0 * ms / stream_build_ms if stream_build_ms > 0 else 0.0,
                100.0 * ms / loop_total if loop_total > 0 else 0.0,
                n,
            )
        # Lo que stream_build mide y este profiler no atribuye al bucle
        # (prefetch diario, swing, qual_lookup, gaps entre fases).
        unacc = stream_build_ms - loop_total
        if unacc > 1.0:
            logger.info(
                "[SUBPHASE] phase=unaccounted ms=%.1f pct_stream_build=%.1f%% "
                "(prefetch/montaje previo al bucle y gaps de medición)",
                unacc, 100.0 * unacc / stream_build_ms if stream_build_ms > 0 else 0.0,
            )


PROF = SubPhaseProfiler()
