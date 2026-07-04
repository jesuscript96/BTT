"""
Logs de fase homogéneos para operación (PRD rendimiento-backtester §03.11).

Una línea greppable por fase y por run:
  [TIMING] phase=<fase> dataset=<id> pairs=<n> ms=<int> extra=<k=v,...>

Fases canónicas: qualifying | stream_build | signals | simulate | aggregate | serialize | total
Complementa (no sustituye) los prints [TIMING] históricos.
"""
import logging
import time

logger = logging.getLogger("backtester.timing")

PHASES = ("qualifying", "stream_build", "signals", "simulate", "aggregate", "serialize", "total")


def log_phase(phase: str, ms: float, dataset: str = "-", pairs: int = -1, **extra) -> None:
    """Emite la línea de timing. Nunca lanza (la telemetría no rompe el backtest)."""
    try:
        extra_s = ",".join(f"{k}={v}" for k, v in extra.items()) or "-"
        logger.info(
            "[TIMING] phase=%s dataset=%s pairs=%s ms=%s extra=%s",
            phase, dataset, int(pairs), int(round(ms)), extra_s,
        )
    except Exception:
        pass


class PhaseTimer:
    """Context manager: with PhaseTimer("signals", dataset=..., pairs_fn=...) as t: ..."""

    def __init__(self, phase: str, dataset: str = "-", **extra):
        self.phase = phase
        self.dataset = dataset
        self.extra = extra
        self.pairs = -1
        self._t0 = None

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        ms = (time.perf_counter() - self._t0) * 1000.0
        if exc_type is not None:
            self.extra["error"] = exc_type.__name__
        log_phase(self.phase, ms, dataset=self.dataset, pairs=self.pairs, **self.extra)
        return False
