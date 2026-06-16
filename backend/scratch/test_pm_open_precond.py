import urllib.request
import json
import time

def run_test():
    base_url = "http://127.0.0.1:8010/api"
    
    # 1. Create a dataset with pm_open filters
    # Test for Gap day, Gap+1, and Gap+2
    dataset_payload = {
        "name": "Test Min Open PM Price Dataset",
        "filters": {
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "min_gap_pct": 10.0,
            "rules": [
                {
                    "metric": "Min Open PM price",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "valueType": "static",
                    "value": "2.5"
                },
                {
                    "metric": "lead_open_1",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "valueType": "static",
                    "value": "3.0"
                },
                {
                    "metric": "lead_open_2",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "valueType": "static",
                    "value": "3.5"
                }
            ]
        }
    }
    
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        f"{base_url}/queries/",
        data=json.dumps(dataset_payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    print("Creating dataset...")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            dataset_id = data["id"]
            print(f"Dataset created successfully! ID: {dataset_id}")
    except Exception as e:
        print(f"Error creating dataset: {e}")
        if hasattr(e, "read"):
            print(e.read().decode("utf-8"))
        return

    # Poll precache status
    print("Waiting for dataset precaching to complete...")
    precache_complete = False
    for i in range(120): # up to 2 minutes
        precache_req = urllib.request.Request(f"{base_url}/queries/precache-status/{dataset_id}")
        try:
            with urllib.request.urlopen(precache_req) as precache_resp:
                precache_data = json.loads(precache_resp.read().decode("utf-8"))
                status = precache_data.get("status")
                percent = precache_data.get("percent", 0.0)
                print(f"Precache status: {status} ({percent}%)")
                if status == "completed":
                    precache_complete = True
                    break
                elif status == "failed":
                    print("Precache failed!")
                    break
        except Exception as pe:
            print(f"Error checking precache status: {pe}")
        time.sleep(2)

    if not precache_complete:
        print("Precache did not complete, aborting backtest.")
        # Clean up and exit
        print(f"Deleting test dataset {dataset_id}...")
        req_del = urllib.request.Request(f"{base_url}/queries/{dataset_id}", method="DELETE")
        try:
            urllib.request.urlopen(req_del)
            print("Dataset deleted successfully.")
        except Exception as e:
            print(f"Error deleting dataset: {e}")
        return

    # 2. Call the backtest endpoint or check qualifying tickers for the dataset
    # We can run a dummy backtest using this dataset
    backtest_payload = {
        "dataset_id": dataset_id,
        "strategy_id": "", # No strategy id needed if we just test qualifying data fetching
        "init_cash": 10000,
        "risk_r": 100,
        "fees": 0.01,
        "slippage": 0.01,
        # We can pass a dummy strategy definition
        "strategy_definition": {
            "name": "Dummy Test Strategy",
            "bias": "long",
            "apply_day": "gap_day",
            "entry_logic": {
                "timeframe": "1m",
                "root_condition": {
                    "type": "group",
                    "operator": "AND",
                    "conditions": []
                }
            },
            "risk_management": {
                "use_hard_stop": True,
                "hard_stop": {"type": "Percentage", "value": 2.0},
                "use_take_profit": True,
                "take_profit": {"type": "Percentage", "value": 6.0},
                "take_profit_mode": "Full",
                "partial_take_profits": []
            }
        }
    }
    
    req_bt = urllib.request.Request(
        f"{base_url}/backtest",
        data=json.dumps(backtest_payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    print("Running backtest using the dataset...")
    try:
        with urllib.request.urlopen(req_bt) as resp:
            bt_data = json.loads(resp.read().decode("utf-8"))
            run_id = bt_data["run_id"]
            print(f"Backtest job submitted! Run ID: {run_id}")
            
            # Poll status
            for _ in range(15):
                status_req = urllib.request.Request(f"{base_url}/backtest/status/{run_id}")
                with urllib.request.urlopen(status_req) as status_resp:
                    status_data = json.loads(status_resp.read().decode("utf-8"))
                    print(f"Status: {status_data['status']}, progress: {status_data['progress']}%")
                    if status_data["status"] in ("completed", "failed"):
                        if status_data["status"] == "failed":
                            print(f"Backtest failed with error: {status_data.get('error')}")
                        else:
                            print("Backtest completed successfully!")
                        break
                time.sleep(1)
    except Exception as e:
        print(f"Error running backtest: {e}")
        if hasattr(e, "read"):
            print(e.read().decode("utf-8"))
            
    # 3. Clean up dataset
    print(f"Deleting test dataset {dataset_id}...")
    req_del = urllib.request.Request(f"{base_url}/queries/{dataset_id}", method="DELETE")
    try:
        urllib.request.urlopen(req_del)
        print("Dataset deleted successfully.")
    except Exception as e:
        print(f"Error deleting dataset: {e}")

if __name__ == "__main__":
    run_test()
