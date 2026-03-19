
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.backtester.engine import BacktestEngine
from app.schemas.strategy import Strategy, EntryLogic, ConditionGroup, IndicatorConfig, IndicatorType, Comparator, RiskManagement, TakeProfitMode, RiskType

def test_ha_logic():
    # 1. Create dummy data
    # Create a simple trend: 10, 11, 12, 13, 14, 15...
    n = 100
    base_time = datetime(2023, 1, 1, 9, 30)
    data = {
        'timestamp': [base_time + timedelta(minutes=i) for i in range(n)],
        'open': [float(10 + i) for i in range(n)],
        'high': [float(10.5 + i) for i in range(n)],
        'low': [float(9.5 + i) for i in range(n)],
        'close': [float(10.2 + i) for i in range(n)],
        'volume': [1000.0] * n,
        'ticker': ['AAPL'] * n
    }
    df = pd.DataFrame(data)

    # 2. Define a strategy using HA
    # Condition: HA Close > SMA(5) calculated ON Heikin-Ashi
    strategy = Strategy(
        name="HA Test",
        bias="long",
        entry_logic=EntryLogic(
            timeframe="1m",
            root_condition=ConditionGroup(
                type="group",
                operator="AND",
                conditions=[
                    {
                        "type": "indicator_comparison",
                        "source": {"name": IndicatorType.HA_CLOSE},
                        "comparator": Comparator.GT,
                        "target": {"name": IndicatorType.SMA, "period": 5, "calc_on_heikin": True}
                    }
                ]
            )
        ),
        risk_management=RiskManagement(
            use_hard_stop=True,
            use_take_profit=True,
            take_profit_mode=TakeProfitMode.FULL,
            hard_stop={"type": RiskType.PERCENTAGE, "value": 2.0},
            take_profit={"type": RiskType.PERCENTAGE, "value": 5.0}
        )
    )

    # 3. Initialize Engine
    engine = BacktestEngine(
        strategies=[strategy],
        weights={strategy.id: 1.0},
        market_data=df,
        initial_capital=10000
    )

    # 4. Generate Signals
    signals = engine.generate_boolean_signals("entry")
    
    print(f"Signals generated. Shape: {signals.shape}")
    print(f"Number of entry signals: {np.sum(signals)}")
    
    # 5. Verify HA data calculation
    ha_df = engine._get_ha_data()
    print("\nHeikin-Ashi Sample (First 5):")
    print(ha_df.head())
    
    # Check HA formulas for index 1
    # HA_Close[1] = (Open[1]+High[1]+Low[1]+Close[1])/4
    # HA_Open[1] = (HA_Open[0] + HA_Close[0]) / 2
    row0 = df.iloc[0]
    row1 = df.iloc[1]
    ha_row0_close = (row0['open'] + row0['high'] + row0['low'] + row0['close']) / 4
    ha_row0_open = (row0['open'] + row0['close']) / 2
    
    expected_ha_row1_open = (ha_row0_open + ha_row0_close) / 2
    actual_ha_row1_open = ha_df.iloc[1]['open']
    
    print(f"\nRow 1 HA Open - Expected: {expected_ha_row1_open:.4f}, Actual: {actual_ha_row1_open:.4f}")
    assert abs(expected_ha_row1_open - actual_ha_row1_open) < 1e-6, "HA Open calculation mismatch!"
    
    print("\nVerification Successful!")

if __name__ == "__main__":
    test_ha_logic()
