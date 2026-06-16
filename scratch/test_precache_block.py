import requests
import time
import sys

BASE_URL = "http://127.0.0.1:8000/api"

def run_tests():
    print("1. Fetching existing queries to copy filters...")
    r = requests.get(f"{BASE_URL}/queries/")
    if r.status_code != 200:
        print("Failed to fetch queries:", r.text)
        sys.exit(1)
        
    queries = r.json()
    if not queries:
        print("No queries found. We will use simple mock filters.")
        filters = {
            "gap_day": {
                "gap_pct_min": 10.0
            }
        }
    else:
        filters = queries[0]["filters"]
        print(f"Copied filters from query: {queries[0]['name']}")

    print("\n2. Creating a new dataset to trigger precaching...")
    dataset_name = f"Test Precache Block {int(time.time())}"
    payload = {
        "name": dataset_name,
        "filters": filters
    }
    r = requests.post(f"{BASE_URL}/queries/", json=payload)
    if r.status_code != 200:
        print("Failed to create dataset:", r.text)
        sys.exit(1)
        
    dataset = r.json()
    dataset_id = dataset["id"]
    print(f"Created dataset: {dataset_name} (ID: {dataset_id})")

    # Let's immediately poll the precache status
    print("\n3. Polling status and attempting to run backtest during load...")
    status_url = f"{BASE_URL}/queries/precache-status/{dataset_id}"
    r_status = requests.get(status_url)
    status_data = r_status.json()
    print("Initial Precache Status:", status_data)

    # Let's immediately try to run backtest
    backtest_payload = {
        "dataset_id": dataset_id,
        "strategy_definition": {
            "name": "Draft Strategy",
            "bias": "SHORT",
            "entry_logic": {"conditions": []},
            "exit_logic": {"conditions": []},
            "risk_management": {"use_hard_stop": False}
        },
        "init_cash": 10000.0,
        "risk_r": 100.0,
        "fees": 0.0,
        "slippage": 0.0
    }
    
    r_bt = requests.post(f"{BASE_URL}/backtest", json=backtest_payload)
    print("Backtest status during load:", r_bt.status_code)
    print("Backtest response detail:", r_bt.json())
    
    # Verify blocking
    if r_bt.status_code != 400 or "Espera a que se cargue" not in r_bt.json().get("detail", ""):
        print("ERROR: Backtest was NOT properly blocked during dataset load!")
    else:
        print("SUCCESS: Backtest was properly blocked during dataset load.")

    # Loop to wait until completion
    print("\n4. Waiting for precaching to complete...")
    start_time = time.time()
    while True:
        r_status = requests.get(status_url)
        status_data = r_status.json()
        print(f"Precache progress: {status_data.get('percent')}% (Status: {status_data.get('status')})")
        if status_data.get("status") in ["completed", "failed"]:
            break
        if time.time() - start_time > 60:
            print("Timeout waiting for precache to complete.")
            break
        time.sleep(2)

    # Now run backtest again
    print("\n5. Running backtest after load completed...")
    r_bt_after = requests.post(f"{BASE_URL}/backtest", json=backtest_payload)
    print("Backtest status after load:", r_bt_after.status_code)
    if r_bt_after.status_code == 200:
        print("SUCCESS: Backtest completed successfully after dataset finished loading!")
        results = r_bt_after.json()
        print("Aggregate Metrics:", list(results.get("aggregate_metrics", {}).keys()))
    else:
        print("ERROR: Backtest failed after load completed:", r_bt_after.text)

if __name__ == "__main__":
    run_tests()
