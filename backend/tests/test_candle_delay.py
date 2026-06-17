import pandas as pd
import numpy as np
from app.services.strategy_engine import translate_strategy, get_lowest_timeframe_mins
from app.services.backtest_service import run_backtest

def test_lowest_timeframe_helper():
    # Test M1
    logic_m1 = {
        "timeframe": "1m",
        "root_condition": {
            "operator": "AND",
            "conditions": []
        }
    }
    assert get_lowest_timeframe_mins(logic_m1) == 1

    # Test M5
    logic_m5 = {
        "timeframe": "5m",
        "root_condition": {
            "operator": "AND",
            "conditions": []
        }
    }
    assert get_lowest_timeframe_mins(logic_m5) == 5

    # Test Nested timeframes
    logic_nested = {
        "timeframe": "15m",
        "root_condition": {
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": 10.0,
                    "timeframe": "5m"
                },
                {
                    "type": "indicator_comparison",
                    "source": {"name": "VWAP"},
                    "comparator": "GREATER_THAN",
                    "target": 9.0,
                    "timeframe": "1m"
                }
            ]
        }
    }
    assert get_lowest_timeframe_mins(logic_nested) == 1


def test_candle_delay_and_session_leakage():
    # Create a DataFrame spanning pre-market and regular hours
    # 09:28:00 to 09:35:00 (8 bars)
    timestamps = pd.date_range("2026-06-01 09:28:00", periods=8, freq="1min")
    
    # We set close = 10.5 only at 09:28 (index 0). All other bars close at 9.5.
    # Since vwap = 10.0, only the 09:28 bar satisfies "close > vwap".
    df = pd.DataFrame({
        "ticker": ["TEST"] * 8,
        "date": ["2026-06-01"] * 8,
        "timestamp": timestamps,
        "open": [10.0] * 8,
        "high": [11.0] * 8,
        "low": [9.0] * 8,
        "close": [10.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5],
        "volume": [1000] * 8,
        "vwap": [10.0] * 8,
    })

    # Strategy definition: close > vwap, bias long, SL/TP percent
    # We set candle_delay = 3 (shifts by (3 - 1) * 1 = 2 bars)
    strategy_def = {
        "name": "Test Session Delay",
        "bias": "long",
        "entry_logic": {
            "timeframe": "1m",
            "candle_delay": 3,
            "root_condition": {
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN",
                        "target": {"name": "VWAP"}
                    }
                ]
            }
        },
        "exit_logic": {
            "timeframe": "1m",
            "root_condition": {
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN",
                        "target": {"name": "VWAP"}
                    }
                ]
            }
        },
        "risk_management": {
            "use_hard_stop": True,
            "hard_stop": {"type": "Percentage", "value": 5.0},
            "use_take_profit": True,
            "take_profit": {"type": "Percentage", "value": 10.0},
            "accept_reentries": False
        }
    }

    # Case 1: All sessions active ("all" or market_sessions is None/empty)
    # The signal at 09:28 should shift by 2 bars to 09:30 and execute there.
    res_all_sessions = run_backtest(
        intraday_df=df.copy(),
        strategy_def=strategy_def,
        market_sessions=["all"],
        init_cash=10000.0,
    )
    assert len(res_all_sessions["trades"]) == 1
    # Check that entry time is 09:30 (09:28 + 2 mins)
    entry_time = pd.to_datetime(res_all_sessions["trades"][0]["entry_time"])
    assert entry_time.time() == pd.Timestamp("09:30:00").time()

    # Case 2: Regular sessions only ("rth")
    # Since 09:28 is outside RTH, the signal at 09:28 should be discarded BEFORE shifting.
    # Therefore, no trade should execute.
    res_rth_only = run_backtest(
        intraday_df=df.copy(),
        strategy_def=strategy_def,
        market_sessions=["rth"],
        init_cash=10000.0,
    )
    assert len(res_rth_only["trades"]) == 0
