
import requests
import json

BASE_URL = "http://localhost:8000/api"

def test_create_strategy():
    payload = {
        "name": "Test Strategy Complex",
        "description": "Strategies with nested conditions",
        "universe_filters": {
            "min_market_cap": 1000000,
            "require_shortable": True,
            "exclude_dilution": True,
            "whitelist_sectors": ["Technology"]
        },
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": { "name": "SMA", "period": 20 },
                        "comparator": "CROSSES_ABOVE",
                        "target": { "name": "VWAP" }
                    },
                    {
                        "type": "group",
                        "operator": "OR",
                        "conditions": [
                            {
                                "type": "price_level_distance",
                                "source": "Close",
                                "level": "Pre-Market High",
                                "comparator": "DISTANCE_GT",
                                "value_pct": 5.0
                            },
                            {
                                "type": "candle_pattern",
                                "pattern": "RED_VOLUME",
                                "lookback": 1,
                                "consecutive_count": 3
                            }
                        ]
                    }
                ]
            }
        },
        "risk_management": {
            "hard_stop": { "type": "Percentage", "value": 2.0 },
            "take_profit": { "type": "Percentage", "value": 6.0 },
            "trailing_stop": { "active": True, "type": "EMA13", "buffer_pct": 0.5 }
        }
    }

    try:
        print("Sending Strategy Payload...")
        response = requests.post(f"{BASE_URL}/strategies/", json=payload)
        
        if response.status_code == 200:
            print("SUCCESS: Strategy created!")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"FAILED: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_create_strategy()
