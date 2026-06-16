import requests

base_url = "http://127.0.0.1:8000"

try:
    print("Fetching saved queries from API...")
    r = requests.get(f"{base_url}/api/queries/", timeout=10)
    if r.status_code == 200:
        queries = r.json()
        print(f"Found {len(queries)} total queries.")
        
        # Sort queries by created_at desc if available
        # The API already orders them by created_at DESC, so the first elements are the newest
        
        print("\n--- LATEST 10 DATASETS ---")
        for i, q in enumerate(queries[:15]):
            qid = q.get("id")
            name = q.get("name")
            created_at = q.get("created_at")
            
            status_r = requests.get(f"{base_url}/api/queries/precache-status/{qid}", timeout=5)
            status_data = status_r.json() if status_r.status_code == 200 else "Error"
            print(f"{i+1}. Name: {name} | Created: {created_at}")
            print(f"   ID: {qid} | Status: {status_data}")
            
        print("\n--- SEARCH FOR 'puro' OR '2 años' ---")
        found = False
        for q in queries:
            name = q.get("name", "")
            if "puro" in name.lower() or "2" in name or "dos" in name:
                qid = q.get("id")
                created_at = q.get("created_at")
                status_r = requests.get(f"{base_url}/api/queries/precache-status/{qid}", timeout=5)
                status_data = status_r.json() if status_r.status_code == 200 else "Error"
                print(f"Name: {name} | Created: {created_at}")
                print(f"  ID: {qid} | Status: {status_data}")
                found = True
        if not found:
            print("No datasets matching 'puro' or '2 años' found.")
            
        print("\n--- RUNNING DATASETS ---")
        running_count = 0
        for q in queries:
            qid = q.get("id")
            name = q.get("name")
            status_r = requests.get(f"{base_url}/api/queries/precache-status/{qid}", timeout=5)
            if status_r.status_code == 200:
                status_data = status_r.json()
                if status_data.get("status") == "running":
                    print(f"Name: {name} | ID: {qid} | Status: {status_data}")
                    running_count += 1
        print(f"Total running datasets: {running_count}")
        
    else:
        print(f"Failed to fetch saved queries: HTTP {r.status_code}")
except Exception as e:
    print("Error querying API:", e)
