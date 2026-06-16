import urllib.request
import json

try:
    print("Connecting to health check...")
    req = urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3)
    print("Health response:", req.read().decode('utf-8'))
except Exception as e:
    print("Health check failed:", e)

try:
    print("Connecting to datasets endpoint...")
    req = urllib.request.urlopen("http://127.0.0.1:8000/api/data/datasets", timeout=3)
    res = json.loads(req.read().decode('utf-8'))
    print(f"Success! Listed {len(res)} datasets.")
except Exception as e:
    print("Datasets check failed:", e)
