import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

for ticker in ["AMS", "MULN"]:
    url = f"http://127.0.0.1:8000/api/ticker-analysis/{ticker}"
    print(f"Querying {url}...")
    try:
        r = requests.get(url, verify=False, timeout=15)
        print("Status code:", r.status_code)
        if r.status_code == 200:
            data = r.json()
            print(f"Gap stats returned for {ticker}:")
            print("Source:", data.get("gap_stats", {}).get("source"))
            print("Gap days count:", data.get("gap_stats", {}).get("gap_days_count"))
            print("Stats:", data.get("gap_stats"))
        else:
            print("Error response:", r.text)
    except Exception as e:
        print(f"Error querying API: {e}")

