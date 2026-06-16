import urllib.request
import json

try:
    url = "http://127.0.0.1:8000/api/data/strategies"
    response = urllib.request.urlopen(url)
    data = json.loads(response.read().decode())
    
    types = set()
    for s in data:
        defn = s.get("definition", {})
        if isinstance(defn, str):
            try:
                defn = json.loads(defn)
            except:
                pass
        
        rm = defn.get("risk_management", {}) if isinstance(defn, dict) else {}
        hs = rm.get("hard_stop", {}) if isinstance(rm, dict) else {}
        hs_type = hs.get("type") if isinstance(hs, dict) else None
        if hs_type:
            types.add(str(hs_type))
            
    print("Unique stop types in database:", list(types))
except Exception as e:
    print("Error:", e)
