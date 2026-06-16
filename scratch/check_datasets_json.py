import requests
import json

url = "http://127.0.0.1:8000/api/data/datasets"
try:
    r = requests.get(url, timeout=10)
    print("Status:", r.status_code)
    data = r.json()
    print(json.dumps(data[:5], indent=2)) # Print first 5 datasets
except Exception as e:
    print("Error:", e)
