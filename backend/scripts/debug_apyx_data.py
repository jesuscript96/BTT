import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def debug():
    token = os.getenv("MOTHERDUCK_TOKEN")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    print("\n📊 Checking APYX 1m data for 2026-01-28:")
    df = con.execute("""
        SELECT * FROM historical_data 
        WHERE ticker = 'APYX' AND CAST(timestamp AS DATE) = '2026-01-28'
        LIMIT 10
    """).fetch_df()
    print(df)
    
    count = con.execute("""
        SELECT COUNT(*) FROM historical_data 
        WHERE ticker = 'APYX' AND CAST(timestamp AS DATE) = '2026-01-28'
    """).fetchone()[0]
    print(f"\nTotal 1m bars for APYX on 2026-01-28: {count}")
    
    con.close()

if __name__ == "__main__":
    debug()
