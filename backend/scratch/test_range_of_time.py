import pandas as pd
import numpy as np
from app.services.indicators import compute_indicator

# Create dummy dataframe representing a day with pre-market and regular session
timestamps = pd.to_datetime([
    '2026-06-05 08:00:00', # PM
    '2026-06-05 08:30:00', # PM
    '2026-06-05 09:30:00', # RTH start
    '2026-06-05 10:00:00', # RTH
    '2026-06-05 16:00:00', # AM start
    '2026-06-05 16:15:00', # AM
])

df = pd.DataFrame({
    'timestamp': timestamps,
    'open': [10.0] * 6,
    'high': [10.5] * 6,
    'low': [9.5] * 6,
    'close': [10.0] * 6,
    'volume': [1000] * 6,
})

# Run compute_indicator for Range of Time
res_rth = compute_indicator("Range of Time", df, ap_session="ap.RTH")
print("RTH Mode Output:")
print(res_rth)

# Assertions
expected = [0.0, 30.0, 0.0, 30.0, 0.0, 15.0]
output_list = list(res_rth)
print(f"Calculated: {output_list}")
print(f"Expected:   {expected}")
if output_list == expected:
    print("SUCCESS: Session-aware Range of Time works perfectly!")
else:
    print("FAILURE: Outputs do not match expected session boundaries.")
