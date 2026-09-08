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

# El segundo test de este fichero (`test_jit_engine_max_reentries`) se borro
# el 2026-08-31 con el motor viejo: ejercitaba `BacktestEngine`, que era
# codigo muerto. Las reentradas de la via VIVA siguen cubiertas por
# test_sim_jit_equivalence, test_n2a_native_equivalence y otros seis.
