from datetime import datetime
import pandas as pd
from fastapi.encoders import jsonable_encoder

# Simulate a Trade dict as outputted by engine.py
ts = pd.Timestamp("2026-01-01 12:12:00")
data = {
    "entry_time": ts,
    "exit_time": pd.Timestamp("2026-01-01 14:15:30")
}

try:
    encoded = jsonable_encoder(data)
    print("jsonable_encoder output:", encoded)
except Exception as e:
    print("Error:", e)
