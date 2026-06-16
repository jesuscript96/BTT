import os
import sys
import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


from dotenv import load_dotenv
load_dotenv()

from app.database import get_db_connection
from app.services.cache_service import get_hot_daily_cache

con = get_db_connection()
cache_df = get_hot_daily_cache()
df = cache_df[cache_df['ticker'] == 'SPCB'].copy()
df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.sort_values('timestamp').reset_index(drop=True)

gap_indices = df[df['pmh_gap_pct'] >= 20.0].index.tolist()
print(f"Total gap days count: {len(gap_indices)}")
recent_gap_indices = gap_indices[-5:] if len(gap_indices) > 5 else gap_indices

print("Recent gap days:")
for idx in recent_gap_indices:
    print(f"Index {idx}: timestamp={df.loc[idx, 'timestamp']}, pmh_gap_pct={df.loc[idx, 'pmh_gap_pct']}")

# Target dates:
all_target_dates = set()
for offset in [0, 1, 2]:
    recent_target_indices = [idx + offset for idx in recent_gap_indices if idx + offset < len(df)]
    recent_sub_df = df.loc[recent_target_indices]
    recent_target_dates = pd.to_datetime(recent_sub_df['timestamp']).dt.strftime('%Y-%m-%d').tolist()
    print(f"Offset {offset} target dates: {recent_target_dates}")
    all_target_dates.update(recent_target_dates)

print(f"All target dates ({len(all_target_dates)}): {sorted(list(all_target_dates))}")
