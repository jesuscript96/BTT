import requests
import json

url = "http://127.0.0.1:8000/api/queries/"

payload = {
    "name": "API Test Dataset",
    "filters": {
        "date_from": "2024-01-01",
        "date_to": "2024-12-31",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "min_gap_pct": None,
        "max_gap_pct": None,
        "min_pm_volume": None,
        "min_rth_volume": None,
        "rules": [
            {
                "metric": "Close Price",
                "operator": "GREATER_THAN_OR_EQUAL",
                "valueType": "static",
                "value": "10.0"
            }
        ]
    }
}

print(f"Sending POST to {url}...")
try:
    r = requests.post(url, json=payload, timeout=30)
    print("Status code:", r.status_code)
    try:
        print("Response JSON:")
        print(json.dumps(r.json(), indent=2))
    except:
        print("Response Text:", r.text)
except Exception as e:
    print("Request failed:", e)

# Also let's list datasets to see if it shows up!
list_url = "http://127.0.0.1:8000/api/data/datasets"
print(f"\nSending GET to {list_url}...")
try:
    r = requests.get(list_url, timeout=30)
    print("Status code:", r.status_code)
    try:
        datasets = r.json()
        print("Datasets found:", len(datasets))
        for d in datasets:
            print(f"- {d.get('name')} (id: {d.get('id')})")
    except:
        print("Response Text:", r.text)
except Exception as e:
    print("Request failed:", e)
