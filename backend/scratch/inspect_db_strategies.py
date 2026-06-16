import urllib.request
import json

try:
    url = "http://127.0.0.1:8000/api/data/strategies"
    response = urllib.request.urlopen(url)
    data = json.loads(response.read().decode())
    
    print(f"Total strategies: {len(data)}")
    for s in data:
        name = s.get("name")
        defn = s.get("definition", {})
        if isinstance(defn, str):
            try:
                defn = json.loads(defn)
            except:
                pass
        
        rm = defn.get("risk_management", {}) if isinstance(defn, dict) else {}
        hs = rm.get("hard_stop", {}) if isinstance(rm, dict) else {}
        hs_type = hs.get("type") if isinstance(hs, dict) else None
        hs_val = hs.get("value") if isinstance(hs, dict) else None
        
        if hs_type and "Market" in str(hs_type):
            print(f"- Name: {name}")
            print(f"  Hard Stop Type: {hs_type}")
            print(f"  Hard Stop Value: {hs_val}")
            print(f"  Use Hard Stop: {rm.get('use_hard_stop')}")
            print()
except Exception as e:
    print("Error:", e)
