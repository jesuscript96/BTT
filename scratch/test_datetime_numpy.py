import pandas as pd
import numpy as np

# Create a numpy datetime64 array representing NY time 09:30
np_dt = np.array(['2024-01-02T09:30:00'], dtype='datetime64[us]')
print("NumPy datetime64:", np_dt)

# Convert to pandas series
ts = pd.to_datetime(np_dt)
print("Pandas Timestamp:", ts)
print("Hour:", ts.hour)
print("Minute:", ts.minute)

# Now check as a Series
df = pd.DataFrame({"timestamp": np_dt})
ts_series = pd.to_datetime(df["timestamp"])
print("Pandas Series dt.hour:", ts_series.dt.hour.values)
print("Pandas Series dt.minute:", ts_series.dt.minute.values)
