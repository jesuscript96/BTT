import requests
import time

url = "http://127.0.0.1:8000/api/market/screener?limit=1000&min_gap_at_open_pct=5"
print(f"Sending request to {url}...")
t0 = time.time()
try:
    r = requests.get(url, timeout=60)
    print(f"Status Code: {r.status_code}")
    print(f"Response Time: {time.time() - t0:.2f}s")
    data = r.json()
    records = data.get("records", [])
    print(f"Records returned: {len(records)}")
    if records:
        print("First record:", records[0])
    print("Stats count:", data.get("stats", {}).get("count"))
except Exception as e:
    print("Error:", e)
