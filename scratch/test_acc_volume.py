import sys
import os
import pandas as pd
import numpy as np

# Add backend to path
sys.path.append(os.path.abspath('backend'))

from app.services.strategy_engine import translate_strategy, _evaluate_single_condition

# Create a mock 1-minute dataframe for a day (390 minutes)
np.random.seed(42)
df = pd.DataFrame({
    'timestamp': pd.date_range('2026-06-05 09:30:00', periods=390, freq='min'),
    'open': np.linspace(100.0, 105.0, 390),
    'high': np.linspace(100.5, 105.5, 390),
    'low': np.linspace(99.5, 104.5, 390),
    'close': np.linspace(100.2, 104.8, 390),
    'volume': np.random.randint(1000, 5000, 390),  # Daily total volume around 1.1 million
})

# Let's verify that the total daily volume is around 1.1 million
print("Total daily volume:", df['volume'].sum())

# Define the condition
# Accumulated Volume >= 10,000,000 (astro value relative to 1.1 million)
cond = {
    "type": "indicator_comparison",
    "source": {
        "name": "Accumulated Volume",
    },
    "comparator": "GREATER_THAN_OR_EQUAL",
    "target": 10000000.0
}

# Evaluate the condition
result = _evaluate_single_condition(cond, df, {})
print("Result type:", type(result))
print("Number of True signals:", result.sum())
print("Is any True?", result.any())
