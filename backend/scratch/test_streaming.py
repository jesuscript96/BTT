import os
import sys
import pandas as pd
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Add backend to sys.path
sys.path.insert(0, os.path.abspath('.'))

from app.services.data_service import fetch_qualifying_data, get_intraday_stream

dataset_id = 'bd49cdb9-a9ff-47d1-8455-061732c1166f'
print(f"Fetching qualifying data...")
df = fetch_qualifying_data(dataset_id)
print(f"Qualifying data shape: {df.shape}")

print("Creating streaming iterator...")
from app.services.data_service import _resolve_filters
filters = _resolve_filters(dataset_id, None, None)
date_from = filters.get("start_date") or filters.get("date_from")
date_to = filters.get("end_date") or filters.get("date_to")

print(f"date_from: {date_from}, date_to: {date_to}")

try:
    stream = get_intraday_stream(df, date_from, date_to)
    print("Stream created:", stream)
    count = 0
    for key, group in stream:
        count += 1
        if count <= 5:
            print(f"\nGroup {count}: key={key}, shape={group.shape}")
            print(group.head(2))
        if count % 50 == 0:
            print(f"Processed {count} groups...")
    print(f"Total groups processed: {count}")
except Exception as e:
    print("Error during streaming:")
    import traceback
    traceback.print_exc()
