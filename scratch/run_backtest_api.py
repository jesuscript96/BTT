import requests
import json

url = "http://127.0.0.1:8000/api/backtest"

# Let's define the strategy with both conditions:
# 1. Accumulated Volume >= 1,000,000
# 2. Close < 10% of Previous Max below the level
strategy_def = {
    "name": "Test Distance Bug",
    "bias": "short", # We will test short first since down arrow is shown in the chart
    "apply_day": "gap_day",
    "postgap_preconditions": [],
    "universe_filters": {
        "require_shortable": False,
        "exclude_dilution": False,
        "whitelist_sectors": []
    },
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Accumulated Volume"},
                    "comparator": "GREATER_THAN_OR_EQUAL",
                    "target": 1000000.0
                },
                {
                    "type": "price_level_distance",
                    "source": {"name": "Bar Close"},
                    "level": {"name": "Previous max", "ap_session": "ap.PM"},
                    "comparator": "DISTANCE_LT",
                    "value_pct": 10.0,
                    "position": "below"
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
    "dataset_id": "bd49cdb9-a9ff-47d1-8455-061732c1166f",
    "strategy_definition": strategy_def,
    "init_cash": 10000.0,
    "risk_r": 100.0,
    "start_date": "2025-01-02",
    "end_date": "2025-01-02"
}

print("Running backtest for bias=short...")
res = requests.post(url, json=payload)
if res.status_code == 200:
    data = res.json()
    trades = data.get("trades", [])
    print(f"Number of trades: {len(trades)}")
    for t in trades:
        print(f"Trade: Ticker={t.get('ticker')}, Date={t.get('date')}, EntryTime={t.get('entry_time')}, EntryPrice={t.get('entry_price')}, PnL={t.get('pnl')}")
else:
    print(f"Error {res.status_code}: {res.text}")

# Test with bias=long as well
strategy_def["bias"] = "long"
print("\nRunning backtest for bias=long...")
res = requests.post(url, json=payload)
if res.status_code == 200:
    data = res.json()
    trades = data.get("trades", [])
    print(f"Number of trades: {len(trades)}")
    for t in trades:
        print(f"Trade: Ticker={t.get('ticker')}, Date={t.get('date')}, EntryTime={t.get('entry_time')}, EntryPrice={t.get('entry_price')}, PnL={t.get('pnl')}")
else:
    print(f"Error {res.status_code}: {res.text}")
