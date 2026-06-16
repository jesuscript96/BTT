import urllib.request
import json

url = "http://localhost:8000/api/strategies/"
try:
    with urllib.request.urlopen(url) as response:
        data = response.read()
        strategies = json.loads(data)
        print(f"Total strategies: {len(strategies)}")
        for s in strategies:
            # Check if this strategy has "PM Open" or similar in entry_logic
            entry_logic_str = json.dumps(s.get('entry_logic', {}))
            if "PM Open" in entry_logic_str or "pm_open" in entry_logic_str.lower():
                print(f"MATCHING STRATEGY:")
                print(f"ID: {s.get('id')}, Name: {s.get('name')}")
                print(f"Bias: {s.get('bias')}, Apply Day: {s.get('apply_day')}")
                print(f"Entry Logic: {json.dumps(s.get('entry_logic'), indent=2)}")
                print(f"Risk Management: {json.dumps(s.get('risk_management'), indent=2)}")
                print("-" * 60)
except Exception as e:
    print(f"Error querying API: {e}")
