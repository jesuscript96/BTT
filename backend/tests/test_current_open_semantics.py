"""
Semántica de "Current Open" y "Day Open" (decisión de producto, Jaume 2026-07-07):

- "Day Open"     = apertura de la sesión regular (RTH open), constante todo el
                   día. Decisión MVP explícita: NO se protege del lookahead
                   cross-sesión (usarlo en premarket es responsabilidad del
                   usuario que configura la estrategia).
- "Current Open" = open de la barra actual (== "Bar Open"). Antes era un alias
                   erróneo de Day Open.

Ninguno está expuesto hoy en el builder del frontend ni usado en estrategias
guardadas (verificado en prod 2026-07-07) — este test fija el contrato para
cuando se expongan.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import numpy as np

from test_n2a_native_equivalence import (_strategy, _cmp, _make_day_df,
                                         _make_daily_stats, _make_arrays)
from app.services.strategy_engine import (compile_strategy_def, translate_strategy,
                                          translate_strategy_native)


def _signals(strategy_def, df, ds):
    compiled = compile_strategy_def(strategy_def)
    assert not compiled.get("_indicator_plan", {}).get("has_special"), \
        "estas estrategias deben ser nativas-elegibles"
    legacy = translate_strategy(df.copy(), strategy_def, ds, compiled=compiled)
    native = translate_strategy_native(_make_arrays(df), compiled, ds)
    l = np.asarray(legacy["entries"], dtype=bool)
    n = np.asarray(native["entries"], dtype=bool)
    assert (l == n).all(), "legacy y nativo divergen"
    return l


def test_current_open_es_open_de_barra_no_day_open():
    df = _make_day_df(seed=11, date="2024-07-09")
    ds = _make_daily_stats(df)

    cur = _signals(_strategy([_cmp({"name": "Close"}, "GREATER_THAN",
                                   {"name": "Current Open"})]), df, ds)
    bar = _signals(_strategy([_cmp({"name": "Close"}, "GREATER_THAN",
                                   {"name": "Bar Open"})]), df, ds)
    day = _signals(_strategy([_cmp({"name": "Close"}, "GREATER_THAN",
                                   {"name": "Day Open"})]), df, ds)

    assert (cur == bar).all(), "Current Open debe comportarse como Bar Open"
    assert not (cur == day).all(), (
        "Current Open no debe seguir siendo un alias de Day Open "
        "(si esto falla con señales idénticas por azar, cambiar el seed)"
    )


def test_day_open_sigue_constante_rth_open():
    """Day Open mantiene su semántica: constante = ds['rth_open'] todo el día."""
    from app.services.strategy_engine import _ri_day_open
    df = _make_day_df(seed=3, date="2024-07-09")
    ds = _make_daily_stats(df)
    arrays = _make_arrays(df)
    o = arrays["open"]; c = arrays["close"]
    vals = _ri_day_open(c, arrays["high"], arrays["low"], o, arrays["volume"],
                        None, None, None, None, None, ds)
    assert np.allclose(vals, ds["rth_open"]), "Day Open = rth_open constante"
