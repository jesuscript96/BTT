import sys
import numpy as np
import pandas as pd

# Add backend directory to Python path
sys.path.append(r"C:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend")

from app.backtester.engine import BacktestEngine
from app.services.indicators import compute_indicator
from app.schemas.strategy import Strategy, IndicatorConfig, IndicatorType

print("Testing JIT engine.py _resolve_indicator vs indicators.py compute_indicator...")

# Create mock intraday data for 1 day
timestamps = pd.to_datetime([
    "2026-06-10 08:30:00",
    "2026-06-10 09:00:00",
    "2026-06-10 09:30:00",
    "2026-06-10 09:31:00",
    "2026-06-10 09:32:00",
    "2026-06-10 09:33:00",
    "2026-06-10 16:00:00",
    "2026-06-10 16:01:00"
])
df = pd.DataFrame({
    'timestamp': timestamps,
    'open': [100.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0],
    'high': [101.0, 102.0, 103.0, 104.0, 105.0, 104.0, 106.0, 107.0],
    'low':  [99.0,  100.0, 101.0, 102.0, 103.0, 103.0, 104.0, 105.0],
    'close': [100.0, 101.0, 102.0, 103.0, 104.0, 103.5, 105.0, 106.0],
    'volume': [1000, 2000, 1500, 3000, 2500, 1200, 500, 800],
    'ticker': ['AAPL'] * 8
})

# Instantiate engine with dummy strategy list
engine = BacktestEngine(
    strategies=[],
    weights={},
    market_data=df,
    initial_capital=10000.0
)

# Test cases for sessions: ap.PM, ap.RTH, ap.AM
sessions = ["ap.PM", "ap.RTH", "ap.AM"]
indicator_types = [IndicatorType.PREVIOUS_MAX, IndicatorType.PREVIOUS_MIN]

all_passed = True

for itype in indicator_types:
    for sess in sessions:
        print(f"\n--- Testing {itype.value} with session: {sess} ---")
        
        # 1. indicators.py computation
        ind_name = "Previous max" if itype == IndicatorType.PREVIOUS_MAX else "Previous min"
        res_ind = compute_indicator(
            name=ind_name,
            df=df,
            ap_session=sess
        )
        
        # 2. engine.py resolve computation
        config = IndicatorConfig(name=itype, ap_session=sess)
        res_jit = engine._resolve_indicator(config, df)
        
        # Compare
        print("indicators.py series:")
        print(res_ind.values)
        print("engine.py JIT series:")
        print(res_jit.values)
        
        # Check matching (allowing for NaNs)
        try:
            pd.testing.assert_series_equal(res_ind, res_jit, check_names=False)
            print(f"PASS: {itype.value} ({sess}) matches perfectly!")
        except AssertionError as e:
            print(f"FAIL: {itype.value} ({sess}) mismatch!")
            print(e)
            all_passed = False

if all_passed:
    print("\nALL PARITY CHECKS PASSED SUCCESSFULLY!")
else:
    print("\nParity check failed!")
    sys.exit(1)
