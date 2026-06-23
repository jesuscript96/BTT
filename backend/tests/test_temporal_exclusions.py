import pandas as pd
import numpy as np
from app.services.backtest_service import run_backtest

def generate_two_days_data():
    # 2026-06-01 (Monday) RTH
    timestamps_1 = pd.date_range("2026-06-01 09:30:00", periods=5, freq="1min")
    # 2026-06-02 (Tuesday) RTH
    timestamps_2 = pd.date_range("2026-06-02 09:30:00", periods=5, freq="1min")
    
    times = list(timestamps_1) + list(timestamps_2)
    dates = ["2026-06-01"] * 5 + ["2026-06-02"] * 5
    
    df = pd.DataFrame({
        "ticker": ["TEST"] * 10,
        "date": dates,
        "timestamp": times,
        "open": [10.0] * 10,
        "high": [11.0] * 10,
        "low": [9.0] * 10,
        "close": [10.5, 9.5, 9.5, 9.5, 9.5, 10.5, 9.5, 9.5, 9.5, 9.5],
        "volume": [1000] * 10,
        "vwap": [10.0] * 10,
    })
    return df

def test_day_and_month_exclusions():
    df = generate_two_days_data()

    # Base strategy: close > vwap triggers long entry
    strategy_def = {
        "name": "Test Exclusions Strategy",
        "bias": "long",
        "entry_logic": {
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
        "exit_logic": {
            "timeframe": "1m",
            "root_condition": {
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN",
                        "target": 100.0  # unrealistic target, will exit at EOD
                    }
                ]
            }
        },
        "risk_management": {
            "use_hard_stop": False,
            "use_take_profit": False,
            "accept_reentries": False,
            "exclude_days": [],
            "exclude_months": [],
            "exclude_days_active": False
        }
    }

    # Case 1: No exclusions active
    res_no_exclusions = run_backtest(
        intraday_df=df.copy(),
        strategy_def=strategy_def.copy(),
        market_sessions=["all"],
        init_cash=10000.0,
    )
    # Triggers once on Monday and once on Tuesday
    assert len(res_no_exclusions["trades"]) == 2

    # Case 2: Exclusions configured but active=False (should still trade on Monday and Tuesday)
    strategy_inactive_exclusions = strategy_def.copy()
    strategy_inactive_exclusions["risk_management"] = {
        **strategy_inactive_exclusions["risk_management"],
        "exclude_days": [0],
        "exclude_days_active": False
    }
    res_inactive = run_backtest(
        intraday_df=df.copy(),
        strategy_def=strategy_inactive_exclusions,
        market_sessions=["all"],
        init_cash=10000.0,
    )
    assert len(res_inactive["trades"]) == 2

    # Case 3: Exclude Mondays (0) active=True
    strategy_exclude_monday = strategy_def.copy()
    strategy_exclude_monday["risk_management"] = {
        **strategy_exclude_monday["risk_management"],
        "exclude_days": [0],  # Mon = 0
        "exclude_days_active": True
    }
    res_exclude_monday = run_backtest(
        intraday_df=df.copy(),
        strategy_def=strategy_exclude_monday,
        market_sessions=["all"],
        init_cash=10000.0,
    )
    # Should only trade on Tuesday
    assert len(res_exclude_monday["trades"]) == 1
    entry_time = pd.to_datetime(res_exclude_monday["trades"][0]["entry_time"])
    assert entry_time.date() == pd.Timestamp("2026-06-02").date()

    # Case 4: Exclude June (5 in 0-based indexing from frontend) active=True
    strategy_exclude_june = strategy_def.copy()
    strategy_exclude_june["risk_management"] = {
        **strategy_exclude_june["risk_management"],
        "exclude_months": [5],  # June = 5 (0-based)
        "exclude_days_active": True
    }
    res_exclude_june = run_backtest(
        intraday_df=df.copy(),
        strategy_def=strategy_exclude_june,
        market_sessions=["all"],
        init_cash=10000.0,
    )
    # Should not trade at all in June
    assert len(res_exclude_june["trades"]) == 0
