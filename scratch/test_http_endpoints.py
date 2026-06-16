import urllib.request
import json

try:
    url = "http://127.0.0.1:8000/api/data/datasets/78c15895-aaed-4e44-920e-19ba17c64f07"
    req = urllib.request.urlopen(url)
    res = req.read().decode('utf-8')
    dataset = json.loads(res)
    print("--- PM 2 Dataset Details ---")
    print(json.dumps(dataset, indent=2))
except Exception as e:
    print(f"Error: {e}")
