
import duckdb
from app.database import get_db_connection
from fastapi.testclient import TestClient
from app.main import app

def test_aggregate_endpoint():
    client = TestClient(app)
    
    print("Testing /api/market/aggregate/intraday endpoint...")
    
    # 1. Test with no filters (defaults)
    # This might return empty if no data for "latest" date or default date logic fails,
    # but let's see. actually default logic in build_screener_query defaults to last 7 days.
    
    # Let's verify we have some data first or use a known date.
    # We used 2026-02-12 in previous verification.
    
    params = {
        "trade_date": "2026-02-05", # Known date with data from previous context
        "min_volume": 1000,
        "limit": 10 # Should be ignored by aggregate query builder which enforces 50, but let's pass it.
    }
    
    try:
        response = client.get("/api/market/aggregate/intraday", params=params)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Status 200. Received {len(data)} data points associated with the aggregation.")
            if len(data) > 0:
                print("First 3 data points:", data[:3])
                # Check structure
                first = data[0]
                if "time" in first and "avg_change" in first and "median_change" in first:
                     print("✅ Data structure correct.")
                else:
                     print("❌ Data structure incorrect:", first.keys())
            else:
                print("⚠️ No data returned. This might be due to no market data for the date/filters.")
        else:
            print(f"❌ Status {response.status_code}: {response.text}")
            
    except Exception as e:
        print(f"❌ Error calling endpoint: {e}")
        import traceback; traceback.print_exc()

if __name__ == "__main__":
    test_aggregate_endpoint()
