import urllib.request
import json
import time

task_id = "opt_1954026487344"

# Poll progress
print("Polling existing task...")
for i in range(120):
    time.sleep(2)
    try:
        progress_req = urllib.request.Request(f"http://127.0.0.1:8000/api/optimization/progress/{task_id}")
        with urllib.request.urlopen(progress_req) as prog_res:
            prog_data = json.loads(prog_res.read().decode("utf-8"))
            print(f"Poll {i+1}: Progress: {prog_data['progress']}%")
            if prog_data["progress"] >= 100:
                break
    except Exception as e:
        print(f"Error polling progress: {e}")

# Get result
try:
    result_req = urllib.request.Request(f"http://127.0.0.1:8000/api/optimization/result/{task_id}")
    with urllib.request.urlopen(result_req) as result_res:
        result_data = json.loads(result_res.read().decode("utf-8"))
        print(f"Result keys: {result_data.keys()}")
        print(f"Shape of grid: {result_data.get('shape')}")
        print(f"Grid preview: {result_data.get('grid')[:2] if 'grid' in result_data else 'No grid'}")
except Exception as e:
    print(f"Error fetching result: {e}")
