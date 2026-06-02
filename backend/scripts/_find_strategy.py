import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.db.gcs_cache import get_strategies_df

df = get_strategies_df()
if df is None or df.empty:
    print("No GCS strategies df")
else:
    print(f"Total GCS strategies: {len(df)}")
    print(df[["id", "name"]].to_string())
