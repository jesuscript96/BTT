import urllib.request
import json

url = "http://localhost:8000/api/queries/"
try:
    with urllib.request.urlopen(url) as response:
        data = response.read()
        queries = json.loads(data)
        found = False
        for q in queries:
            name = q['name']
            if "3" in name or "meses" in name.lower() or "rapida" in name.lower() or "rápida" in name.lower():
                print(f"ID: {q['id']}, Name: {q['name']}")
                print(f"Filters: {json.dumps(q['filters'], indent=2)}")
                print("-" * 60)
                found = True
        if not found:
            print("Not found by name filters, listing first 10 queries:")
            for q in queries[:10]:
                print(f"ID: {q['id']}, Name: {q['name']}")
                print("-" * 30)
except Exception as e:
    print(f"Error querying API: {e}")
