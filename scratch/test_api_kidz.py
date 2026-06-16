import requests

url_gap = "http://127.0.0.1:8000/api/ticker-analysis/KIDZ/gap-stats"
url_chart = "http://127.0.0.1:8000/api/ticker-analysis/KIDZ/chart"

try:
    print("Calling gap-stats API...")
    r_gap = requests.get(url_gap, timeout=5)
    print("Gap Stats Status:", r_gap.status_code)
    if r_gap.status_code == 200:
        data = r_gap.json()
        print("\nGap Stats response keys:", list(data.keys()))
        print("know_the_float:", data.get("know_the_float"))
        print("gap_stats count:", data.get("gap_stats", {}).get("gap_days_count"))
        print("gap_stats source:", data.get("gap_stats", {}).get("source"))
        print("gap_stats details:", data.get("gap_stats"))
    else:
        print("Error response:", r_gap.text)
        
    print("\nCalling chart API...")
    r_chart = requests.get(url_chart, timeout=5)
    print("Chart Status:", r_chart.status_code)
    if r_chart.status_code == 200:
        chart_data = r_chart.json()
        daily_history = chart_data.get("daily_history", [])
        print(f"Total days in daily_history: {len(daily_history)}")
        if len(daily_history) > 0:
            print(f"First day in history: {daily_history[0]['time']}")
            print(f"Last day in history: {daily_history[-1]['time']}")
            
            # Let's count gaps manually from the daily_history returned by the backend
            gaps_20 = []
            gaps_10 = []
            for i in range(1, len(daily_history)):
                prev_c = daily_history[i-1]["close"]
                curr_o = daily_history[i]["open"]
                if prev_c and curr_o and prev_c > 0:
                    gap_pct = (curr_o - prev_c) / prev_c * 100
                    if gap_pct >= 20.0:
                        gaps_20.append((daily_history[i]["time"], gap_pct))
                    elif gap_pct >= 10.0:
                        gaps_10.append((daily_history[i]["time"], gap_pct))
            
            print(f"\nManual calculation from chart daily_history:")
            print(f"Number of gaps >= 20%: {len(gaps_20)}")
            for date, g in gaps_20:
                print(f"  {date}: {g:.2f}%")
            print(f"Number of gaps 10% - 20%: {len(gaps_10)}")
            for date, g in gaps_10[:10]:
                print(f"  {date}: {g:.2f}%")
except Exception as e:
    print("Error:", e)
