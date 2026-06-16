import requests
import time

ticker = "MULN"
endpoints = {
    "profile": f"http://127.0.0.1:8000/api/ticker-analysis/{ticker}",
    "sec-filings": f"http://127.0.0.1:8000/api/ticker-analysis/{ticker}/sec-filings",
    "chart": f"http://127.0.0.1:8000/api/ticker-analysis/{ticker}/chart",
    "balance-sheet": f"http://127.0.0.1:8000/api/ticker-analysis/{ticker}/balance-sheet",
    "gap-stats": f"http://127.0.0.1:8000/api/ticker-analysis/{ticker}/gap-stats",
    "finviz-news": f"http://127.0.0.1:8000/api/ticker-analysis/{ticker}/finviz-news"
}

for name, url in endpoints.items():
    print(f"Testing {name} ({url})...")
    start = time.time()
    try:
        r = requests.get(url, timeout=25)
        duration = time.time() - start
        print(f"[{name}] Status: {r.status_code}, Time: {duration:.2f}s")
        if r.status_code != 200:
            print(f"[{name}] Response: {r.text[:200]}")
    except Exception as e:
        duration = time.time() - start
        print(f"[{name}] FAILED after {duration:.2f}s: {e}")
