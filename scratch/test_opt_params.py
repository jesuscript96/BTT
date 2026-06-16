import urllib.request
import json

url = "http://127.0.0.1:8000/api/optimization/parameters"
headers = {"Content-Type": "application/json"}
data = {
    "strategy_id": "draft",
    "strategy_definition": {
        "name": "Draft Strategy",
        "bias": "short",
        "apply_day": "gap_day",
        "postgap_preconditions": [],
        "entry_logic": {
            "root_condition": {
                "operator": "AND",
                "conditions": []
            }
        },
        "exit_logic": {
            "root_condition": {
                "operator": "AND",
                "conditions": []
            }
        },
        "risk_management": {
            "use_hard_stop": True,
            "hard_stop": {
                "type": "Market Structure (HOD/LOD)",
                "value": "PMH"
            }
        }
    }
}

req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")

try:
    with urllib.request.urlopen(req) as res:
        status = res.status
        body = res.read().decode("utf-8")
        print(f"STATUS: {status}")
        print(f"RESPONSE: {body}")
except Exception as e:
    print(f"ERROR: {e}")
