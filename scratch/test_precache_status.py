import urllib.request
import json

url = "http://127.0.0.1:8000/api/queries/precache-status/78c15895-aaed-4e44-920e-19ba17c64f07"
try:
    print(f"Fetching status from {url}...")
    req = urllib.request.urlopen(url)
    res = json.loads(req.read().decode('utf-8'))
    print("Precache Status Response:")
    print(json.dumps(res, indent=2))
except Exception as e:
    print("Failed:", e)
