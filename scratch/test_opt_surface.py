import urllib.request
import json
import time

# Get datasets
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/api/data/datasets") as res:
        datasets = json.loads(res.read().decode("utf-8"))
except Exception as e:
    print(f"Error fetching datasets: {e}")
    datasets = []

if not datasets:
    print("No datasets available.")
    exit(1)

dataset_id = datasets[0]["id"]
print(f"Using dataset: {dataset_id}")

# Let's trigger optimization/surface
url = "http://127.0.0.1:8000/api/optimization/surface"
headers = {"Content-Type": "application/json"}
data = {
    "strategy_id": "draft",
    "strategy_definition": {
        "name": "Draft Strategy",
        "bias": "short",
        "apply_day": "gap_day",
        "postgap_preconditions": [],
        "entry_logic": {
            "root_condition": {
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "timeframe": "1m",
                        "source": {
                            "name": "SMA",
                            "period": 20
                        },
                        "comparator": "GREATER_THAN",
                        "target": 10.0
                    }
                ]
            }
        },
        "exit_logic": {
            "root_condition": {
                "operator": "AND",
                "conditions": []
            }
        },
        "risk_management": {
            "use_hard_stop": True,
            "hard_stop": {
                "type": "Market Structure (HOD/LOD)",
                "value": "PMH"
            }
        }
    },
    "dataset_id": dataset_id,
    "metric": "sharpe",
    "param_configs": [
        {
            "id": "entry_logic.root_condition.conditions.0.source.period",
            "label": "SMA Period",
            "path": "entry_logic.root_condition.conditions.0.source.period",
            "min": 10.0,
            "max": 30.0,
            "steps": 3
        }
    ],
    "init_cash": 10000.0,
    "risk_r": 100.0,
    "risk_type": "FIXED",
    "size_by_sl": False,
    "fees": 0.0,
    "fee_type": "PERCENT",
    "monthly_expenses": 0.0,
    "slippage": 0.0,
    "start_date": None,
    "end_date": None,
    "market_sessions": ["rth"],
    "custom_start_time": None,
    "custom_end_time": None,
    "locates_cost": 0.0,
    "look_ahead_prevention": True
}

req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")

try:
    with urllib.request.urlopen(req) as res:
        res_data = json.loads(res.read().decode("utf-8"))
        print(f"Surface sweep initiated: {res_data}")
        task_id = res_data["task_id"]
        
        # Poll progress
        for _ in range(30):
            time.sleep(1)
            progress_req = urllib.request.Request(f"http://127.0.0.1:8000/api/optimization/progress/{task_id}")
            with urllib.request.urlopen(progress_req) as prog_res:
                prog_data = json.loads(prog_res.read().decode("utf-8"))
                print(f"Progress: {prog_data['progress']}%")
                if prog_data["progress"] >= 100:
                    break
        
        # Get result
        result_req = urllib.request.Request(f"http://127.0.0.1:8000/api/optimization/result/{task_id}")
        with urllib.request.urlopen(result_req) as result_res:
            result_data = json.loads(result_res.read().decode("utf-8"))
            print(f"Result keys: {result_data.keys()}")
            print(f"Success! Shape of grid: {result_data.get('shape')}")
except Exception as e:
    print(f"ERROR: {e}")
