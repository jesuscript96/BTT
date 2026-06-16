import requests
import json

# Fetch datasets first
datasets_url = "http://127.0.0.1:8000/api/data/datasets"
print("Fetching datasets...")
try:
    res = requests.get(datasets_url)
    if res.status_code == 200:
        datasets = res.json()
        print(f"Found {len(datasets)} datasets:")
        for ds in datasets[:5]:
            print(f"  Name: {ds.get('name')}, ID: {ds.get('id')}")
        if not datasets:
            print("No datasets found.")
            exit(1)
        
        # Search for a dataset with pairs
        dataset_id = None
        min_date = None
        max_date = None
        for ds in datasets:
            curr_id = ds.get('id')
            query_url = f"http://127.0.0.1:8000/api/data/datasets/{curr_id}"
            res_ds = requests.get(query_url)
            if res_ds.status_code == 200:
                ds_data = res_ds.json()
                pair_count = ds_data.get("pair_count", 0)
                if pair_count > 0:
                    dataset_id = curr_id
                    min_date = ds_data.get("min_date")
                    max_date = ds_data.get("max_date")
                    print(f"Using dataset: {ds.get('name')} ({curr_id}) with {pair_count} pairs, date range: {min_date} to {max_date}")
                    break
        
        if not dataset_id:
            print("No datasets with pair_count > 0 found.")
            exit(1)
    else:
        print(f"Error listing datasets: {res.status_code} - {res.text}")
        exit(1)
except Exception as e:
    print("Failed to fetch datasets:", e)
    exit(1)

# Pick date range
date = min_date
# Let's run a backtest with a strategy definition
backtest_url = "http://127.0.0.1:8000/api/backtest"
strategy_def = {
    "name": "Test Entry Time Windows",
    "bias": "long",
    "apply_day": "gap_day",
    "postgap_preconditions": [],
    "universe_filters": {
        "require_shortable": False,
        "exclude_dilution": False,
        "whitelist_sectors": []
    },
    "entry_logic": {
        "timeframe": "1m",
        "entry_time_windows": [
            {"from_time": "09:30", "to_time": "11:30"}
        ],
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": 0.0
                }
            ]
        }
    },
    "exit_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": []
        }
    },
    "risk_management": {
        "use_hard_stop": True,
        "use_take_profit": True,
        "take_profit_mode": "Full",
        "accept_reentries": True,
        "hard_stop": {"type": "Percentage", "value": 5.0},
        "take_profit": {"type": "Percentage", "value": 5.0},
        "partial_take_profits": [],
        "trailing_stop": {"active": False, "type": "Percentage", "buffer_pct": 0.5}
    }
}

payload = {
    "dataset_id": dataset_id,
    "strategy_definition": strategy_def,
    "init_cash": 10000.0,
    "risk_r": 100.0,
    "start_date": "2024-01-02",
    "end_date": "2024-01-31",
    "market_sessions": ["pre", "rth", "post"]
}

print(f"\nRunning backtest for dataset_id={dataset_id}, date 2024-01-02 to 2024-01-31 with entry_time_windows: 09:30 - 11:30...")
res = requests.post(backtest_url, json=payload)
if res.status_code == 200:
    data = res.json()
    trades = data.get("trades", [])
    print(f"Number of trades: {len(trades)}")
    outside_window_count = 0
    for t in trades:
        entry_time = t.get("entry_time") # format: ISO string or similar
        print(f"Trade: Ticker={t.get('ticker')}, EntryTime={entry_time}, ExitTime={t.get('exit_time')}, Reason={t.get('exit_reason')}")
        # Parse time part of entry_time
        # Usually entry_time is like "2025-01-02T09:35:00"
        time_str = entry_time.split("T")[1][:5] if "T" in entry_time else entry_time.split(" ")[1][:5]
        h, m = map(int, time_str.split(":"))
        mins = h * 60 + m
        if mins < 9*60+30 or mins > 11*60+30:
            print(f"  --> WARNING: Trade entered OUTSIDE entry window: {time_str}")
            outside_window_count += 1
    if outside_window_count == 0:
        print("\nSUCCESS: All entries are within the time window!")
    else:
        print(f"\nFAILURE: {outside_window_count} entries were outside the time window!")
else:
    print(f"Error {res.status_code}: {res.text}")
