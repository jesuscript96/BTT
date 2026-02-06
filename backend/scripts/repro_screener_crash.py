import sys
import os
import traceback

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import requests
from app.routers.market import screen_market

# Base URL
BASE_URL = "http://localhost:8000/api/market/screener"

# Params from the user report
PARAMS = {
    "min_gap": 0,
    "min_run": 0,
    "min_volume": 0,
    "limit": 100,
    "ticker": "niu"
}

def test_screener():
    print(f"Testing GET {BASE_URL} with params: {PARAMS}")
    try:
        response = requests.get(BASE_URL, params=PARAMS)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print("Response Text:")
            print(response.text)
        else:
            print("Success!")
            data = response.json()
            print(f"Records: {len(data.get('records', []))}")
            
    except Exception as e:
        print(f"Request failed: {e}")

def test_screener_internal():
    print("Testing screen_market() internal...")
    try:
        result = screen_market(
            min_gap=0,
            min_run=0,
            min_volume=0,
            limit=100,
            ticker="niu"
        )
        print("Success!")
        stats = result.get('stats', {}).get('averages', {})
        print(f"Stats Sample: {stats}")
        # Check for NaNs
        import math
        has_nan = any(isinstance(v, float) and math.isnan(v) for v in stats.values())
        print(f"Has NaNs: {has_nan}")
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    test_screener_internal() 
    # test_screener()
