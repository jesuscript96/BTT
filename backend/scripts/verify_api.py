import requests
import json

base_url = "http://localhost:8000/api/market"
params = {
    "min_gap_at_open_pct": 30,
    "max_gap_at_open_pct": 50,
    "min_volume": 150000000,
    "start_date": "2025-11-15",
    "end_date": "2026-02-16",
    "limit": 5000
}

print("Testing /screener...")
r_screen = requests.get(f"{base_url}/screener", params=params)
if r_screen.status_code == 200:
    data = r_screen.json()
    recs = data.get('records', [])
    print(f"Screener Records: {len(recs)}")
    if len(recs) > 0:
        print(f"Sample Ticker: {recs[0]['ticker']} on {recs[0]['date']}")
    print(f"Screener Stats count: {data.get('stats', {}).get('count')}")
else:
    print(f"Screener Error {r_screen.status_code}: {r_screen.text}")

print("\nTesting /aggregate/intraday...")
r_agg = requests.get(f"{base_url}/aggregate/intraday", params=params)
if r_agg.status_code == 200:
    data = r_agg.json()
    print(f"Aggregate Results: {len(data)} time points")
else:
    print(f"Aggregate Error {r_agg.status_code}: {r_agg.text}")
