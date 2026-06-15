import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from app.backtester.engine import BacktestEngine
from app.schemas.strategy import Strategy

def generate_mock_two_days_data():
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

def test_swing_option_active():
    df = generate_mock_two_days_data()
    
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
            "accept_reentries": False,
            "swing_option": {
                "active": True,
                "target_day": "gap_1_day"
            }
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
    
    res = engine.run()
    trades = res.trades
    
    assert len(trades) == 1
    exit_dt = pd.to_datetime(trades[0]["exit_time"])
    assert exit_dt.date() == pd.to_datetime("2026-06-16").date()
    assert trades[0]["exit_reason"] == "End of Day"

def test_swing_option_inactive():
    df = generate_mock_two_days_data()
    
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
            "accept_reentries": False,
            "swing_option": {
                "active": False,
                "target_day": "gap_1_day"
            }
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
    
    res = engine.run()
    trades = res.trades
    
    assert len(trades) == 1
    exit_dt = pd.to_datetime(trades[0]["exit_time"])
    assert exit_dt.date() == pd.to_datetime("2026-06-15").date()
    assert trades[0]["exit_reason"] == "End of Day"
