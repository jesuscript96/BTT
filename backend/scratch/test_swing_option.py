import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Add backend to sys.path
sys.path.insert(0, os.path.abspath('.'))

from app.backtester.engine import BacktestEngine
from app.schemas.strategy import Strategy, RiskManagement, EntryLogic, ConditionGroup, Timeframe

def generate_mock_two_days_data():
    # Generate 1-minute bars for Day 0 (9:30 to 16:00) and Day 1 (9:30 to 16:00)
    # Day 0: 2026-06-15
    # Day 1: 2026-06-16
    bars = []
    
    # 2026-06-15 RTH
    start_dt_1 = datetime(2026, 6, 15, 9, 30)
    for i in range(390):
        dt = start_dt_1 + timedelta(minutes=i)
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
        
    # 2026-06-16 RTH
    start_dt_2 = datetime(2026, 6, 16, 9, 30)
    for i in range(390):
        dt = start_dt_2 + timedelta(minutes=i)
        bars.append({
            "ticker": "TEST",
            "timestamp": dt,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000,
            "date": "2026-06-16"
        })
        
    df = pd.DataFrame(bars)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df

def test_swing_option():
    print("=== Testing Swing Option JIT and Simulation ===")
    df = generate_mock_two_days_data()
    
    # Create simple strategy
    # Entry logic: always true (True for every bar)
    # Exit logic: empty (never exits by exit logic)
    strategy_data = {
        "id": "strat_test_swing",
        "name": "Test Swing Strategy",
        "bias": "long",
        "apply_day": "gap_day",
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": []
            }
        },
        "risk_management": {
            "use_hard_stop": True,
            "hard_stop": {"type": "Percentage", "value": 5.0},
            "use_take_profit": True,
            "take_profit": {"type": "Percentage", "value": 10.0},
            "accept_reentries": False, # Only one trade allowed
            "swing_option": {
                "active": True,
                "target_day": "gap_1_day"
            }
        }
    }
    
    # Verify Strategy parsing
    strategy = Strategy(**strategy_data)
    
    # Run backtest with swing_option active
    engine = BacktestEngine(
        strategies=[strategy],
        weights={strategy.id: 1.0},
        market_data=df,
        commission_per_trade=0.0,
        initial_capital=10000.0,
        max_holding_minutes=3000
    )
    
    res = engine.run()
    trades = res.trades
    print(f"Swing Option ACTIVE: {len(trades)} trades simulated.")
    for t in trades:
        print(f"Trade: Entry={t['entry_time']}, Exit={t['exit_time']}, Reason={t['exit_reason']}")
        
    assert len(trades) == 1, "Expected exactly 1 trade"
    exit_dt = pd.to_datetime(trades[0]["exit_time"])
    assert exit_dt.date() == pd.to_datetime("2026-06-16").date(), f"Expected exit on 2026-06-16, got {exit_dt.date()}"
    assert trades[0]["exit_reason"] == "End of Day", f"Expected exit reason End of Day, got {trades[0]['exit_reason']}"
    
    # Now run backtest with swing_option inactive
    strategy_data_inactive = strategy_data.copy()
    strategy_data_inactive["risk_management"]["swing_option"]["active"] = False
    strategy_inactive = Strategy(**strategy_data_inactive)
    
    engine_inactive = BacktestEngine(
        strategies=[strategy_inactive],
        weights={strategy_inactive.id: 1.0},
        market_data=df,
        commission_per_trade=0.0,
        initial_capital=10000.0,
        max_holding_minutes=1000
    )
    
    res_inactive = engine_inactive.run()
    trades_inactive = res_inactive.trades
    print(f"Swing Option INACTIVE: {len(trades_inactive)} trades simulated.")
    for t in trades_inactive:
        print(f"Trade: Entry={t['entry_time']}, Exit={t['exit_time']}, Reason={t['exit_reason']}")
        
    assert len(trades_inactive) == 1, "Expected exactly 1 trade"
    exit_dt_inactive = pd.to_datetime(trades_inactive[0]["exit_time"])
    assert exit_dt_inactive.date() == pd.to_datetime("2026-06-15").date(), f"Expected exit on 2026-06-15, got {exit_dt_inactive.date()}"
    assert trades_inactive[0]["exit_reason"] == "End of Day", f"Expected exit reason End of Day, got {trades_inactive[0]['exit_reason']}"
    
    print("\nSwing Option verification SUCCESSFUL!")

if __name__ == "__main__":
    test_swing_option()
