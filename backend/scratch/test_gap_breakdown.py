import sys
import os
import time

# Add parent directory to path so we can import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.routers.ticker_analysis import scrape_knowthefloat, get_gap_stats_all_days

ticker = "AAPL"

print(f"1. Measuring scrape_knowthefloat('{ticker}')...")
t0 = time.time()
float_data = scrape_knowthefloat(ticker)
t1 = time.time()
print(f"   Time taken: {t1 - t0:.2f}s")
print(f"   Data found: {list(float_data.keys())}")

print(f"\n2. Measuring get_gap_stats_all_days('{ticker}')...")
t0 = time.time()
gap_data = get_gap_stats_all_days(ticker)
t1 = time.time()
print(f"   Time taken: {t1 - t0:.2f}s")
print(f"   Gap stats data keys: {list(gap_data.keys())}")
if "gap_stats" in gap_data:
    print(f"   Gap days count: {gap_data['gap_stats'].get('gap_days_count')}")
