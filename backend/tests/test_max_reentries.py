import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from app.services.portfolio_sim import simulate
from app.schemas.strategy import Strategy

def test_portfolio_sim_max_reentries():
    # Generate 10 bars
    n = 10
    close = np.array([100.0] * n)
    open_ = np.array([100.0] * n)
    high = np.array([101.0] * n)
    low = np.array([99.0] * n)
    
    # Entry signal at bar 1, 3, 5, 7
    entries = np.array([False, True, False, True, False, True, False, True, False, False])
    # Exit signal at bar 2, 4, 6, 8
    exits = np.array([False, False, True, False, True, False, True, False, True, False])
    
    # Test max_reentries = 2 (total trades: 1 initial + 2 reentries = 3)
    res = simulate(
        close=close,
        open_=open_,
        high=high,
        low=low,
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=10000.0,
        risk_r=100.0,
        risk_type="FIXED",
        accumulate=True,
        max_reentries=2,
        sl_stop=0.02, # 2% SL
        tp_stop=0.06, # 6% TP
    )
    assert len(res["trades"]) == 3, f"Expected 3 trades, got {len(res['trades'])}"

    # Test max_reentries = 0 (total trades: 1 initial + 0 reentries = 1)
    res_0 = simulate(
        close=close,
        open_=open_,
        high=high,
        low=low,
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=10000.0,
        risk_r=100.0,
        risk_type="FIXED",
        accumulate=True,
        max_reentries=0,
        sl_stop=0.02,
        tp_stop=0.06,
    )
    assert len(res_0["trades"]) == 1, f"Expected 1 trade, got {len(res_0['trades'])}"

    # Test max_reentries = -1 (infinite reentries)
    res_inf = simulate(
        close=close,
        open_=open_,
        high=high,
        low=low,
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=10000.0,
        risk_r=100.0,
        risk_type="FIXED",
        accumulate=True,
        max_reentries=-1,
        sl_stop=0.02,
        tp_stop=0.06,
    )
    assert len(res_inf["trades"]) > 3

def _datos_reentradas():
    n = 10
    return dict(
        close=np.array([100.0] * n), open_=np.array([100.0] * n),
        high=np.array([101.0] * n), low=np.array([99.0] * n),
        entries=np.array([False, True, False, True, False, True, False, True, False, False]),
        exits=np.array([False, False, True, False, True, False, True, False, True, False]),
        direction="longonly", init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        sl_stop=0.02, tp_stop=0.06,
    )


import pytest  # noqa: E402


@pytest.mark.parametrize("motor", ["py", "jit"])
@pytest.mark.parametrize("accumulate, max_re, esperado", [
    (False, 2, 1),     # 30-sep (Jaume): apagado = cero reentradas aunque N = 2
    (False, -1, 1),
    (False, 0, 1),
    (True, 2, 3),      # encendido + N = 2 -> 1 + 2 reentradas
    (True, 0, 1),      # encendido + N = 0 -> cero reentradas
    (True, -1, 4),     # encendido + -1 -> sin tope (las 4 senales)
], ids=["off-N2", "off-m1", "off-0", "on-N2", "on-0", "on-m1"])
def test_reentradas_interruptor_manda(motor, accumulate, max_re, esperado):
    """Regla del 30-sep: el interruptor de reentradas manda sobre `max_reentries`, en los dos motores."""
    if motor == "py":
        sim = simulate
    else:
        from app.services.sim_dispatch import simulate_jit as sim
    res = sim(**_datos_reentradas(), accumulate=accumulate, max_reentries=max_re)
    assert len({t["entry_idx"] for t in res["trades"]}) == esperado


@pytest.mark.parametrize("accept, max_re, hechas, quedan", [
    (False, 2, 0, True),
    (False, 2, 1, False),   # 30-sep: apagado + N = 2 -> no avisa una segunda entrada
    (False, -1, 1, False),
    (True, 2, 2, True),
    (True, 2, 3, False),
    (True, 0, 1, False),
    (True, -1, 9, True),
])
def test_bot_alertas_quedan_entradas_misma_regla(accept, max_re, hechas, quedan):
    """El bot de alertas (`_quedan_entradas`) sigue la misma regla que el motor."""
    from app.services.bot_alerts_engine import MotorAlertas
    trades = [{"entry_idx": i} for i in range(hechas)]
    senales = {"accept_reentries": accept, "max_reentries": max_re}
    assert MotorAlertas._quedan_entradas(trades, senales) is quedan


# El segundo test de este fichero (`test_jit_engine_max_reentries`) se borro
# el 2026-08-31 con el motor viejo: ejercitaba `BacktestEngine`, que era
# codigo muerto. Las reentradas de la via VIVA siguen cubiertas por
# test_sim_jit_equivalence, test_n2a_native_equivalence y otros seis.
