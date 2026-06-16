import requests
import json

url = "http://127.0.0.1:8000/api/market/aggregate/intraday"

# Test 1m
print("--- Testing 1m Interval ---")
res_1m = requests.get(url, params={"min_gap_at_open_pct": 20.0, "interval": 1})
print(f"1m Status Code: {res_1m.status_code}")
data_1m = res_1m.json()
print(f"1m Data size: {len(data_1m)}")
if data_1m:
    print(f"First data point: {data_1m[0]}")
    print(f"Second data point: {data_1m[1]}")

# Test 15m
print("\n--- Testing 15m Interval ---")
res_15m = requests.get(url, params={"min_gap_at_open_pct": 20.0, "interval": 15})
print(f"15m Status Code: {res_15m.status_code}")
data_15m = res_15m.json()
print(f"15m Data size: {len(data_15m)}")
if data_15m:
    print(f"First data point: {data_15m[0]}")
    print(f"Second data point: {data_15m[1]}")
    print(f"Third data point: {data_15m[2]}")
    print(f"Last data point: {data_15m[-1]}")
