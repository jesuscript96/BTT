import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def check_pk():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if token:
        token = token.strip()
    
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    print("\n📊 Checking daily_metrics schema:")
    df = con.execute("PRAGMA table_info('daily_metrics')").fetch_df()
    print(df[['name', 'type', 'pk']])
    con.close()

if __name__ == "__main__":
    check_pk()
