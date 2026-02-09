import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def verify(ticker):
    token = os.getenv("MOTHERDUCK_TOKEN")
    if token:
        token = token.strip()
    
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    print(f"\n📊 Verifying Ticker: {ticker}")
    
    # Query data
    res = con.execute("""
        SELECT date, pm_high, low_spike_pct, hod_time 
        FROM daily_metrics 
        WHERE ticker = ? 
        AND low_spike_pct IS NOT NULL
        ORDER BY date DESC 
        LIMIT 5
    """, [ticker]).fetch_df()
    
    if res.empty:
        print(f"❌ No enriched data found for {ticker}")
    else:
        print("✅ Enriched data found:")
        print(res)
        
    con.close()

if __name__ == "__main__":
    verify("RUBI")
    verify("RELI")
