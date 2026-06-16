import os
import sys
import pandas as pd

# Change directory to backend/ so imports work correctly
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

from app.services.cache_service import get_hot_daily_cache

hot_df = get_hot_daily_cache()
if hot_df is not None and not hot_df.empty:
    print("Hot cache columns:")
    for col in sorted(hot_df.columns):
        print(f"  {col}")
else:
    print("Hot cache is empty or None")
