import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def find_any():
    token = os.getenv("MOTHERDUCK_TOKEN")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    print("\n📊 Recent 1m bars in historical_data:")
    df = con.execute("""
        SELECT ticker, CAST(timestamp AS DATE) as date, COUNT(*) as c 
        FROM historical_data 
        GROUP BY ticker, date 
        ORDER BY date DESC, c DESC 
        LIMIT 10
    """).fetch_df()
    print(df)
    con.close()

if __name__ == "__main__":
    find_any()
