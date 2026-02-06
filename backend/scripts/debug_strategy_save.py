import requests
import json

BASE_URL = "http://localhost:8000/api/strategies/"

# Payload mimicking the user's attempt
# They likely entered a name and hit save without adding confirmed conditions.
payload = {
    "name": "TESTEO NIO CORTO",
    "description": "",
    "filters": {
        "min_market_cap": None,
        "max_market_cap": None,
        "max_shares_float": None,
        "require_shortable": True,
        "exclude_dilution": True
    },
    "entry_logic": [
        {
            "id": "default-group",
            "conditions": [],
            "logic": "AND"
        }
    ],
    "exit_logic": {
        "stop_loss_type": "Percent",
        "stop_loss_value": None, # Simulating NaN/Empty input
        "take_profit_type": "Percent",
        "take_profit_value": 10.0,
        "trailing_stop_active": False,
        "trailing_stop_type": "EMA13",
        "dilution_profit_boost": False # Check if this matches schema default
    }
}

def test_save():
    print("Attempting to save strategy...")
    try:
        response = requests.post(BASE_URL, json=payload)
        print(f"Status: {response.status_code}")
        if response.status_code != 200:
            print("Response:")
            try:
                print(json.dumps(response.json(), indent=2))
            except:
                print(response.text)
        else:
            print("Success!")
            print(response.json())
    except Exception as e:
        print(f"Request Error: {e}")

if __name__ == "__main__":
    test_save()
