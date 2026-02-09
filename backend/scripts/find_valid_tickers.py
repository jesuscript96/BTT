import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def find_data():
    token = os.getenv("MOTHERDUCK_TOKEN")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    print("\n📊 Top tickers by 1m bar count:")
    df = con.execute("""
        SELECT ticker, COUNT(*) as c 
        FROM historical_data 
        GROUP BY ticker 
        ORDER BY c DESC 
        LIMIT 10
    """).fetch_df()
    print(df)
    con.close()

if __name__ == "__main__":
    find_data()
