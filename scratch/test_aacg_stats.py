import os
import sys
import time
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

from app.services.cache_service import load_hot_daily_cache
from app.routers.ticker_analysis import get_gap_stats_all_days

print("Loading hot daily cache...")
load_hot_daily_cache()

print("Starting calculation for AACG...")
start = time.time()
try:
    res = get_gap_stats_all_days("AACG")
    end = time.time()
    print(f"Success! Time taken: {end - start:.2f} seconds")
    print("Keys in result:", res.keys())
    for k, v in res.items():
        if isinstance(v, dict):
            chart_len = len(v.get("price_change_chart", []))
            print(f"  {k}: gap_days_count={v.get('gap_days_count')}, price_change_chart_len={chart_len}")
            if chart_len > 0:
                print(f"    Sample chart point: {v['price_change_chart'][0]}")
except Exception as e:
    print("Error calling get_gap_stats_all_days:", e)
