import urllib.request
import json

url = "http://127.0.0.1:8000/api/data/strategies"
try:
    print(f"Fetching strategies from {url}...")
    req = urllib.request.urlopen(url)
    res = json.loads(req.read().decode('utf-8'))
    print(f"Found {len(res)} strategies.")
    if res:
        print("Sample Strategy:")
        print(json.dumps(res[0], indent=2))
except Exception as e:
    print("Failed:", e)
