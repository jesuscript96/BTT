"""
EPIC A (PRD rendimiento-backtester §03.11) — formato de los logs de fase.

Contrato: una línea greppable
  [TIMING] phase=<fase> dataset=<id> pairs=<n> ms=<int> extra=<k=v,...>
"""
import logging
import re

import pytest

from app.services.perf_timing import PHASES, PhaseTimer, log_phase

LINE_RE = re.compile(
    r"^\[TIMING\] phase=(?P<phase>[a-z_]+) dataset=(?P<dataset>\S+) "
    r"pairs=(?P<pairs>-?\d+) ms=(?P<ms>\d+) extra=(?P<extra>\S+)$"
)


def _only_timing(caplog):
    return [r for r in caplog.records if r.name == "backtester.timing"]


def test_log_phase_format(caplog):
    with caplog.at_level(logging.INFO, logger="backtester.timing"):
        log_phase("signals", 1234.56, dataset="ds_1", pairs=35000, workers=6)
    recs = _only_timing(caplog)
    assert len(recs) == 1
    m = LINE_RE.match(recs[0].getMessage())
    assert m, f"formato inválido: {recs[0].getMessage()!r}"
    assert m["phase"] == "signals"
    assert m["dataset"] == "ds_1"
    assert m["pairs"] == "35000"
    assert m["ms"] == "1235"
    assert "workers=6" in m["extra"]


def test_log_phase_defaults(caplog):
    with caplog.at_level(logging.INFO, logger="backtester.timing"):
        log_phase("total", 10.2)
    m = LINE_RE.match(_only_timing(caplog)[0].getMessage())
    assert m and m["dataset"] == "-" and m["pairs"] == "-1" and m["extra"] == "-"


@pytest.mark.parametrize("phase", PHASES)
def test_canonical_phases_parse(phase, caplog):
    with caplog.at_level(logging.INFO, logger="backtester.timing"):
        log_phase(phase, 1.0)
    assert LINE_RE.match(_only_timing(caplog)[0].getMessage())


def test_phase_timer_measures_and_sets_pairs(caplog):
    with caplog.at_level(logging.INFO, logger="backtester.timing"):
        with PhaseTimer("simulate", dataset="ds_2") as t:
            t.pairs = 7
    m = LINE_RE.match(_only_timing(caplog)[0].getMessage())
    assert m and m["phase"] == "simulate" and m["pairs"] == "7"
    assert int(m["ms"]) >= 0


def test_phase_timer_logs_on_exception(caplog):
    with caplog.at_level(logging.INFO, logger="backtester.timing"):
        with pytest.raises(ValueError):
            with PhaseTimer("signals"):
                raise ValueError("boom")
    m = LINE_RE.match(_only_timing(caplog)[0].getMessage())
    assert m and "error=ValueError" in m["extra"]


def test_log_phase_never_raises():
    class Weird:
        def __str__(self):
            raise RuntimeError("no str")
    log_phase("total", 1.0, extra_obj=Weird())  # no debe lanzar
