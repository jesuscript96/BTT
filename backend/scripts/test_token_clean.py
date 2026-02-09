import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def test_connection():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        print("❌ No token found in .env")
        return
        
    # Clean the token
    cleaned_token = token.strip()
    print(f"Token length: {len(token)} -> {len(cleaned_token)}")
    
    try:
        print("Connecting with cleaned token...")
        con = duckdb.connect(f"md:btt?motherduck_token={cleaned_token}")
        print("✅ Connected successfully!")
        res = con.execute("SELECT count(*) FROM daily_metrics").fetchone()
        print(f"Daily Metrics Count: {res[0]}")
        con.close()
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    test_connection()
