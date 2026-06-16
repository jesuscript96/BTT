import requests
import time

endpoints = {
    "profile": "http://127.0.0.1:8000/api/ticker-analysis/AAPL",
    "sec-filings": "http://127.0.0.1:8000/api/ticker-analysis/AAPL/sec-filings",
    "chart": "http://127.0.0.1:8000/api/ticker-analysis/AAPL/chart",
    "balance-sheet": "http://127.0.0.1:8000/api/ticker-analysis/AAPL/balance-sheet",
    "gap-stats": "http://127.0.0.1:8000/api/ticker-analysis/AAPL/gap-stats",
    "finviz-news": "http://127.0.0.1:8000/api/ticker-analysis/AAPL/finviz-news"
}

for name, url in endpoints.items():
    print(f"Testing {name} ({url})...")
    start = time.time()
    try:
        r = requests.get(url, timeout=15)
        duration = time.time() - start
        print(f"[{name}] Status: {r.status_code}, Time: {duration:.2f}s")
        if r.status_code != 200:
            print(f"[{name}] Response: {r.text[:200]}")
    except Exception as e:
        duration = time.time() - start
        print(f"[{name}] FAILED after {duration:.2f}s: {e}")
