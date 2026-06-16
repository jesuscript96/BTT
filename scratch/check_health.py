import urllib.request
import json

url = "http://localhost:8000/health"
try:
    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode('utf-8'))
        print(f"Health response: {data}")
except Exception as e:
    print(f"Health check failed: {e}")
