
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.backtester.engine import BacktestEngine
from app.schemas.strategy import Strategy, EntryLogic, ConditionGroup, IndicatorConfig, IndicatorType, Comparator, RiskManagement, TakeProfitMode, RiskType, PriceLevelDistanceCondition

def test_final_enhancements():
    # 1. Create dummy data (2 days for 1 ticker)
    n = 100
    base_time = datetime(2023, 1, 1, 9, 30)
    data = {
        'timestamp': [base_time + timedelta(minutes=i) if i < 50 else base_time + timedelta(days=1, minutes=i-50) for i in range(n)],
        'open': [10.0 + i for i in range(n)],
        'high': [10.5 + i for i in range(n)],
        'low': [9.5 + i for i in range(n)],
        'close': [10.2 + i for i in range(n)],
        'volume': [1000.0] * n,
        'ticker': ['AAPL'] * n
    }
    df = pd.DataFrame(data)

    # Strategy: Price (Close) Distance to Day Open
    # Condition: Close is > 5% ABOVE Day Open
    strat = Strategy(
        name="Final Test",
        bias="long",
        entry_logic=EntryLogic(
            timeframe="1m",
            root_condition=ConditionGroup(
                type="group",
                conditions=[
                    {
                        "type": "price_level_distance",
                        "source": {"name": IndicatorType.CLOSE},
                        "level": {"name": IndicatorType.DAY_OPEN},
                        "comparator": "DISTANCE_GT",
                        "value_pct": 5.0,
                        "position": "above"
                    }
                ]
            )
        ),
        risk_management=RiskManagement(take_profit_mode=TakeProfitMode.FULL, hard_stop={"type": RiskType.PERCENTAGE, "value": 2}, take_profit={"type": RiskType.PERCENTAGE, "value": 5})
    )

    # Run Engine
    engine = BacktestEngine(strategies=[strat], weights={strat.id: 1.0}, market_data=df)
    
    signals = engine.generate_boolean_signals("entry")
    
    # Day 1 Open is 10.0 (row 0)
    # Target: 10.0 * 1.05 = 10.5
    # Success starts when Close > 10.5
    # Row 1 Close is 11.2 (10.2 + 1) -> Should be True
    print(f"Row 0 Close: {df.iloc[0]['close']}, Day Open: {df.iloc[0]['open']} -> Signal: {signals[0, 0]}")
    print(f"Row 1 Close: {df.iloc[1]['close']}, Day Open: {df.iloc[1]['open']} -> Signal: {signals[1, 0]}")
    
    # Day 2 Open is 10.0 + 50 = 60.0 (row 50)
    # Target: 60.0 * 1.05 = 63.0
    # Row 50 Close is 60.2 -> False
    # Row 53 Close is 63.2 -> True
    print(f"Row 50 Close: {df.iloc[50]['close']}, Day Open: {df.iloc[50]['open']} -> Signal: {signals[50, 0]}")
    print(f"Row 53 Close: {df.iloc[53]['close']}, Day Open: {df.iloc[53]['open']} -> Signal: {signals[53, 0]}")

    assert signals[1, 0] == True, "Day 1 Signal failed!"
    assert signals[53, 0] == True, "Day 2 Signal failed!"
    assert signals[50, 0] == False, "Day 2 Signal (low) failed!"

    print("\nVerification Successful!")

if __name__ == "__main__":
    test_final_enhancements()
