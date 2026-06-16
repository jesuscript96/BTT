import sys
sys.path.append(".")
from app.services.cache_service import get_hot_daily_cache
import pandas as pd

df = get_hot_daily_cache()
if df is not None:
    print("Columns:", list(df.columns))
    print("Shape:", df.shape)
    aapl_df = df[df['ticker'] == 'AAPL']
    print("AAPL rows in hot cache:", len(aapl_df))
    if not aapl_df.empty:
        print(aapl_df.head(2))
else:
    print("Hot cache is None")
