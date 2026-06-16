import requests
import json

url = "http://127.0.0.1:8000/api/market/aggregate/intraday"
params = {
    "min_gap_at_open_pct": 20.0
}

try:
    print("Sending request to backend...")
    res = requests.get(url, params=params)
    print(f"Status Code: {res.status_code}")
    data = res.json()
    print(f"Data size: {len(data)}")
    if data:
        print("First 5 minutes of aggregated data:")
        print(json.dumps(data[:5], indent=2))
        print("Last 5 minutes of aggregated data:")
        print(json.dumps(data[-5:], indent=2))
    else:
        print("Empty response data")
except Exception as e:
    print(f"Error calling API: {e}")
