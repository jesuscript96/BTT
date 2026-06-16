import os
import sys
import pandas as pd
import numpy as np

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.services.strategy_engine import _eval_price_level_distance
from app.backtester.engine import BacktestEngine
from app.schemas.strategy import PriceLevelDistanceCondition, IndicatorConfig, IndicatorType

# 1. Create mock data
# PM High level = 100.0
data = {
    "timestamp": pd.date_range("2026-06-07 09:30:00", periods=4, freq="min"),
    "open": [105.0, 100.0, 95.0, 85.0],
    "high": [105.0, 100.0, 95.0, 85.0],
    "low": [105.0, 100.0, 95.0, 85.0],
    "close": [105.0, 100.0, 95.0, 85.0],
    "volume": [1000, 1000, 1000, 1000]
}
df = pd.DataFrame(data)
daily_stats = {"pm_high": 100.0}

def test_production_engine(position_value, expected_results, test_name):
    cond = {
        "type": "price_level_distance",
        "source": {"name": "Bar Close"},
        "level": {"name": "Pre-Market High"},
        "comparator": "DISTANCE_LT",
        "value_pct": 10.0,
        "position": position_value
    }
    
    try:
        res = _eval_price_level_distance(cond, df, daily_stats)
        results = res.tolist()
        print(f"\n--- Production Test: {test_name} (position={position_value}) ---")
        print(f"Prices:  {df['close'].tolist()}")
        print(f"Results: {results}")
        print(f"Expected:{expected_results}")
        
        if results == expected_results:
            print("PASS")
            return True
        else:
            print("FAIL")
            return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def test_jit_engine(position_value, expected_results, test_name):
    # Setup dummy BacktestEngine
    # We just need it to run _evaluate_distance, which does not require strategies to be fully populated for this method
    engine = BacktestEngine(strategies=[], weights={}, market_data=df)
    
    # Pre-populate some required columns in df if needed
    # PM High in market_data
    df["pm_high"] = 100.0
    
    cond = PriceLevelDistanceCondition(
        type="price_level_distance",
        source=IndicatorConfig(name=IndicatorType.BAR_CLOSE),
        level=IndicatorConfig(name=IndicatorType.PMH),
        comparator="DISTANCE_LT",
        value_pct=10.0,
        position=position_value
    )
    
    try:
        # Resolve indicators requires BacktestEngine
        res = engine._evaluate_distance(cond, df)
        results = res.tolist()
        print(f"\n--- JIT Test: {test_name} (position={position_value}) ---")
        print(f"Prices:  {df['close'].tolist()}")
        print(f"Results: {results}")
        print(f"Expected:{expected_results}")
        
        if results == expected_results:
            print("PASS")
            return True
        else:
            print("FAIL")
            return False
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

print("Running verification tests for strategy_engine.py and engine.py...")

# Test 1: position="below"
t1_prod = test_production_engine("below", [False, True, True, False], "Below Level Filter (Inclusive)")
t1_jit = test_jit_engine("below", [False, True, True, False], "Below Level Filter (Inclusive)")

# Test 2: position=None
t2_prod = test_production_engine(None, [True, True, True, False], "None / Null fallback to Any")
t2_jit = test_jit_engine(None, [True, True, True, False], "None / Null fallback to Any")

# Test 3: position="above"
t3_prod = test_production_engine("above", [True, True, False, False], "Above Level Filter")
t3_jit = test_jit_engine("above", [True, True, False, False], "Above Level Filter")

# Test 4: position="any"
t4_prod = test_production_engine("any", [True, True, True, False], "Any Position")
t4_jit = test_jit_engine("any", [True, True, True, False], "Any Position")

if all([t1_prod, t1_jit, t2_prod, t2_jit, t3_prod, t3_jit, t4_prod, t4_jit]):
    print("\nALL TESTS PASSED!")
    sys.exit(0)
else:
    print("\nSOME TESTS FAILED!")
    sys.exit(1)
