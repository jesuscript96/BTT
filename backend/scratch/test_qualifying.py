import os
import sys
import pandas as pd
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Add backend to sys.path
sys.path.insert(0, os.path.abspath('.'))

from app.services.data_service import fetch_qualifying_data

print("DB_PROVIDER:", os.getenv("DB_PROVIDER"))
print("GCS_BUCKET:", os.getenv("GCS_BUCKET"))

dataset_id = 'bd49cdb9-a9ff-47d1-8455-061732c1166f'
print(f"Fetching qualifying data for dataset: {dataset_id}")

try:
    df = fetch_qualifying_data(dataset_id)
    print("Success!")
    print("DataFrame shape:", df.shape)
    if not df.empty:
        print("Columns:", df.columns.tolist())
        print("First 5 rows:")
        print(df.head(5))
    else:
        print("DataFrame is empty!")
except Exception as e:
    print("Error during fetch_qualifying_data:")
    import traceback
    traceback.print_exc()
