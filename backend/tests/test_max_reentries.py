import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from app.services.portfolio_sim import simulate
from app.backtester.engine import BacktestEngine
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

def test_jit_engine_max_reentries():
    # Create mock DataFrame for BacktestEngine
    bars = []
    start_dt = datetime(2026, 6, 15, 9, 30)
    
    # We want 10 bars
    # Bar 1 (9:31): Entry signal
    # Bar 2 (9:32): Exit signal (Close position)
    # Bar 3 (9:33): Entry signal
    # Bar 4 (9:34): Exit signal
    # Bar 5 (9:35): Entry signal
    # Bar 6 (9:36): Exit signal
    # Bar 7 (9:37): Entry signal
    # Bar 8 (9:38): Exit signal
    
    for i in range(10):
        dt = start_dt + timedelta(minutes=i)
        bars.append({
            "ticker": "TEST",
            "timestamp": dt,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000,
            "date": "2026-06-15"
        })
    df = pd.DataFrame(bars)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    
    # Let's modify volume in df to control the entries and exits:
    # Bar 0 (9:30): vol=0 (no entry)
    # Bar 1 (9:31): vol=1000 (entry signal)
    # Bar 2 (9:32): vol=100 (no entry, position open)
    # Bar 3 (9:33): vol=5 (exit signal)
    # Bar 4 (9:34): vol=1000 (entry signal)
    # Bar 5 (9:35): vol=5 (exit signal)
    # Bar 6 (9:36): vol=1000 (entry signal, should NOT enter because limit of 1 reentry has been reached)
    df.loc[0, "volume"] = 0.0
    df.loc[1, "volume"] = 1000.0
    df.loc[2, "volume"] = 100.0
    df.loc[3, "volume"] = 5.0
    df.loc[4, "volume"] = 1000.0
    df.loc[5, "volume"] = 5.0
    df.loc[6, "volume"] = 1000.0
    df.loc[7, "volume"] = 5.0
    
    # Setup custom indicators so entry_signals/exit_signals can be generated
    # The engines uses strategy rules, let's create a strategy definition
    strategy_data = {
        "id": "strat_max_reentries",
        "name": "Test Max Reentries",
        "bias": "long",
        "apply_day": "gap_day",
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Volume"},
                        "comparator": "GREATER_THAN",
                        "target": 500.0
                    }
                ]
            }
        },
        "exit_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Volume"},
                        "comparator": "LESS_THAN",
                        "target": 10.0
                    }
                ]
            }
        },
        "risk_management": {
            "use_hard_stop": True,
            "use_take_profit": True,
            "take_profit_mode": "Full",
            "accept_reentries": True,
            "max_reentries": 1, # limit to 1 reentry (total 2 trades)
            "hard_stop": {"type": "Percentage", "value": 2.0},
            "take_profit": {"type": "Percentage", "value": 6.0},
            "trailing_stop": {"active": False, "type": "Percentage", "buffer_pct": 0.5}
        }
    }
    
    strategy = Strategy(**strategy_data)
    engine = BacktestEngine(
        strategies=[strategy],
        weights={strategy.id: 1.0},
        market_data=df,
        commission_per_trade=0.0,
        initial_capital=10000.0,
        max_holding_minutes=3000
    )
    
    # Let's run backtest!
    results = engine.run()
    
    # Check trades list in results
    trades = results.trades
    # Total trades should be exactly 2 (initial trade + 1 reentry)
    assert len(trades) == 2, f"Expected 2 trades in JIT, got {len(trades)}"
