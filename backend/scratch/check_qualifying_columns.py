import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.abspath('.'))

from app.services.data_service import fetch_qualifying_data

df = fetch_qualifying_data(
    "bd49cdb9-a9ff-47d1-8455-061732c1166f",
    None,
    None,
    preconditions=[],
    apply_day="gap_day"
)

print("Columns in qualifying_df:")
print(df.columns.tolist())
print("\nShape of qualifying_df:", df.shape)
print("\nSample lead_timestamp_1:")
if "lead_timestamp_1" in df.columns:
    print(df["lead_timestamp_1"].head(10))
else:
    print("lead_timestamp_1 is NOT in columns!")
