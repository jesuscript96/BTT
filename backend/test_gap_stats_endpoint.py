import os
import sys
import json
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

from app.routers.ticker_analysis import get_ticker_gap_stats

# Let's call get_ticker_gap_stats for VSME
ticker = "VSME"
print(f"Calling get_ticker_gap_stats for {ticker}...")
try:
    res = get_ticker_gap_stats(ticker)
    print("\nKeys in response:", res.keys())
    for k in ["gap_stats", "gap_stats_plus_1", "gap_stats_plus_2"]:
        stats = res[k]
        chart = stats.get("price_change_chart", [])
        print(f"\n{k}:")
        print(f"  gap_days_count: {stats.get('gap_days_count')}")
        print(f"  high_rth_spike_avg: {stats.get('high_rth_spike_avg')}")
        print(f"  price_change_chart length: {len(chart)}")
        if len(chart) > 0:
            print(f"  First 3 chart points: {chart[:3]}")
            print(f"  Last 3 chart points: {chart[-3:]}")
        else:
            print("  Chart is empty!")
except Exception as e:
    print(f"Error calling get_ticker_gap_stats: {e}")
