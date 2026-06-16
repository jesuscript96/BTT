import requests
import json

url = "http://127.0.0.1:8000/api/candles"
params = {
    "dataset_id": "bd49cdb9-a9ff-47d1-8455-061732c1166f",
    "ticker": "AEI",
    "date": "2025-01-02"
}

res = requests.get(url, params=params)
if res.status_code == 200:
    data = res.json()
    print(f"Data type: {type(data)}")
    if isinstance(data, dict):
        candles = data.get("candles", [])
        print(f"Length of candles: {len(candles)}")
        if len(candles) > 0:
            print("Keys of first candle:")
            print(candles[0].keys())
            print("First 5 candles:")
            print(json.dumps(candles[:5], indent=2))
else:
    print(f"Error {res.status_code}: {res.text}")
