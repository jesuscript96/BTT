import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def debug():
    token = os.getenv("MOTHERDUCK_TOKEN")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    print("\n📊 Checking MULN 1m data for 2025-07-25:")
    df = con.execute("""
        SELECT * FROM historical_data 
        WHERE ticker = 'MULN' AND CAST(timestamp AS DATE) = '2025-07-25'
        LIMIT 10
    """).fetch_df()
    print(df)
    
    count = con.execute("""
        SELECT COUNT(*) FROM historical_data 
        WHERE ticker = 'MULN' AND CAST(timestamp AS DATE) = '2025-07-25'
    """).fetchone()[0]
    print(f"\nTotal 1m bars for MULN on 2025-07-25: {count}")
    
    con.close()

if __name__ == "__main__":
    debug()
