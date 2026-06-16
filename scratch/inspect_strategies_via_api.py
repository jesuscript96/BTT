import urllib.request
import json

url = "http://127.0.0.1:8000/api/strategies/"
print(f"Fetching strategies from API: {url} ...")
try:
    with urllib.request.urlopen(url) as response:
        html = response.read().decode('utf-8')
        strategies = json.loads(html)
        print(f"Found {len(strategies)} strategies:")
        for idx, s in enumerate(strategies):
            print(f"[{idx}] Strategy Name: {s.get('name')}")
            print(f"    ID: {s.get('id')}")
            print(f"    Bias: {s.get('bias')}")
            entry_logic = s.get("entry_logic", {})
            print("    Entry Logic:")
            print(f"      Timeframe: {entry_logic.get('timeframe')}")
            print(f"      Entry Time Windows: {entry_logic.get('entry_time_windows')}")
            print("-" * 50)
except Exception as e:
    print("Error:", e)
