
import requests
import json
import random

BASE_URL = "http://localhost:8000"

def create_dumb_strategy():
    # 1. Create a dummy strategy if not exists
    strat = {
      "name": "Test Strat " + str(random.randint(1000,9999)),
      "description": "Auto generated",
      "universe_filters": {},
      "risk_management": {
          "hard_stop": {"type": "Percentage", "value": 2.0},
          "take_profit": {"type": "Percentage", "value": 6.0}
      },
      "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Close"},
                    "comparator": "GREATER_THAN",
                    "target": {"name": "Open"}
                }
            ]
        }
      }
    }
    
    try:
        res = requests.post(f"{BASE_URL}/api/strategies/", json=strat)
        if res.status_code == 200:
            return res.json()['id']
    except:
        pass
    return None

def test_backtest():
    
    strat_id = create_dumb_strategy()
    if not strat_id:
        print("Could not create strategy, trying to fetch existing...")
        try:
            strats = requests.get(f"{BASE_URL}/api/strategies/").json()
            if strats:
                strat_id = strats[0]['id']
            else:
                print("No strategies found.")
                return
        except Exception as e:
            print(f"Error fetching strats: {e}")
            return

    print(f"Using Strategy: {strat_id}")
    
    payload = {
      "strategy_ids": [strat_id],
      "weights": {strat_id: 100.0},
      "dataset_filters": {
        # Using a wide filter to ensure we get SOME data
        "min_volume": 100000,
        "start_date": "2024-01-01", 
        "end_date": "2024-01-30" # Short range for speed
      },
      "initial_capital": 100000,
      "max_holding_minutes": 390
    }
    
    print("Sending Backtest Request...")
    try:
        res = requests.post(f"{BASE_URL}/api/backtest/run", json=payload)
        if res.status_code == 200:
            data = res.json()
            print("SUCCESS!")
            print(f"Run ID: {data['run_id']}")
            print(f"Trades: {data['results']['total_trades']}")
            print(f"Win Rate: {data['results']['win_rate']}%")
        else:
            print(f"FAILED: {res.status_code}")
            print(res.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_backtest()
