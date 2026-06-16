import requests
import json

ticker = "KIDZ"

print("=== Chart Endpoint ===")
url_chart = f"http://127.0.0.1:8000/api/ticker-analysis/{ticker}/chart"
try:
    r = requests.get(url_chart, timeout=10)
    print("Status:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        history = data.get("daily_history", [])
        print("Total trading days returned:", len(history))
        if history:
            print("First day:", history[0]["time"])
            print("Last day:", history[-1]["time"])
            
            # Count gaps >= 20% in chart daily history
            gaps = []
            for i in range(1, len(history)):
                prev_close = history[i-1]["close"]
                curr_open = history[i]["open"]
                if prev_close and curr_open:
                    gap_pct = (curr_open - prev_close) / prev_close * 100
                    if gap_pct >= 20.0:
                        gaps.append((history[i]["time"], gap_pct))
            print("Gaps >= 20% found in chart history:", len(gaps))
            for g in gaps:
                print(f"  Date: {g[0]}, Gap: {g[1]:.2f}%")
except Exception as e:
    print("Error querying chart endpoint:", e)

print("\n=== Gap Stats Endpoint ===")
url_gap_stats = f"http://127.0.0.1:8000/api/ticker-analysis/{ticker}/gap-stats"
try:
    r = requests.get(url_gap_stats, timeout=10)
    print("Status:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        print("Gap days count (offset 0):", data.get("gap_stats", {}).get("gap_days_count"))
        print("Source:", data.get("gap_stats", {}).get("source"))
        print("Gap Stats (offset 0):", json.dumps(data.get("gap_stats"), indent=2))
except Exception as e:
    print("Error querying gap-stats endpoint:", e)
