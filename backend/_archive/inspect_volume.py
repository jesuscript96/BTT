import duckdb
import os

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Imp2YWxlbnp1ZWxhLmNodWxpYUBnbWFpbC5jb20iLCJtZFJlZ2lvbiI6ImF3cy11cy1lYXN0LTEiLCJzZXNzaW9uIjoianZhbGVuenVlbGEuY2h1bGlhLmdtYWlsLmNvbSIsInBhdCI6IlVYQXRaLTI2M2JwWEhHSkxSTVFrUVpENHg5RlozY091dTNneTVKOE00RkkiLCJ1c2VySWQiOiJiYzZmNmEzOC00NmU1LTQzNTgtODIyMS0zY2VhZjJhYzM5NzkiLCJpc3MiOiJtZF9wYXQiLCJyZWFkT25seSI6ZmFsc2UsInRva2VuVHlwZSI6InJlYWRfd3JpdGUiLCJpYXQiOjE3NzAzNDAwNDB9.w1g65spA7RDYyYpRKPhMmnJkz87MLb3uWQSsQvLpQfc"

print("Connecting to MotherDuck...")
con = duckdb.connect(f"md:btt?motherduck_token={token}")
print("Connected.")

# Check AAPL metrics
print("\n--- AAPL Volume Data ---")
df = con.execute("""
    SELECT 
        date, 
        ticker, 
        rth_volume, 
        pm_volume 
    FROM daily_metrics 
    WHERE ticker = 'AAPL' 
    ORDER BY date DESC 
    LIMIT 5
""").fetch_df()
print(df)
