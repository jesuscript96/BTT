import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from .database import get_db_connection

load_dotenv()

API_KEY = os.getenv("MASSIVE_API_KEY")
BASE_URL = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")

class MassiveClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {API_KEY}"})

    def get_tickers(self):
        url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers"
        try:
            response = self.session.get(url, params={"apiKey": API_KEY})
            response.raise_for_status()
            return response.json().get("tickers", [])
        except Exception as e:
            print(f"Error fetching tickers: {e}")
            return []

    def get_aggregates(self, ticker, from_date, to_date, multiplier=1, timespan="minute"):
        # Limits: 5 calls per minute on free tier. 
        # The scheduler handles the timing (62s).
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        try:
            response = self.session.get(url, params={"limit": 50000, "apiKey": API_KEY})
            if response.status_code == 429:
                print(f"⚠️ Rate limited by Massive API for {ticker}")
                return []
            response.raise_for_status()
            return response.json().get("results", [])
        except Exception as e:
            print(f"Error fetching aggregates for {ticker}: {e}")
            return []

def pulse_ingest_cycle():
    """
    Core MVP Logic: Failsafe, rate-limited pulse.
    Fetches the 5 oldest updated tickers and pulls their history.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Pulse started...")
    con = get_db_connection()
    
    # Identify 5 tickers to update
    try:
        tickers = con.execute("""
            SELECT ticker FROM tickers 
            WHERE active = true 
            ORDER BY last_updated ASC 
            LIMIT 5
        """).fetch_df()['ticker'].tolist()
        
        if not tickers:
            print("No tickers found to ingest.")
            return

        client = MassiveClient()
        
        for ticker in tickers:
            days_to_pull = 730 # 2 years for deep history
            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=days_to_pull)).strftime("%Y-%m-%d")
            
            print(f"  -> Pulling {ticker} deep history ({from_date} to {to_date})...")
            ingest_ticker_history_range(client, ticker, from_date, to_date, con=con)
            
            # Mark as updated
            con.execute("UPDATE tickers SET last_updated = ? WHERE ticker = ?", [datetime.now(), ticker])
            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Pulse complete (5 tickers processed).")
    except Exception as e:
        print(f"Pulse error: {e}")
    finally:
        con.close()

def ingest_ticker_history_range(client, ticker, from_date, to_date, con=None):
    """
    Downloads and saves history for a ticker in manageable chunks.
    """
    start_dt = datetime.strptime(from_date, "%Y-%m-%d")
    end_dt = datetime.strptime(to_date, "%Y-%m-%d")
    
    # 45-day chunks to stay safely under Massive 50k result limit (1m bars)
    chunk_size = 45
    current_start = start_dt
    
    while current_start < end_dt:
        current_end = min(current_start + timedelta(days=chunk_size), end_dt)
        fs = current_start.strftime("%Y-%m-%d")
        ts = current_end.strftime("%Y-%m-%d")
        
        print(f"    - Fetching chunk {fs} to {ts}...")
        candles = client.get_aggregates(ticker, fs, ts)
        
        if candles:
            df = pd.DataFrame(candles)
            df = df.rename(columns={
                'v': 'volume', 'o': 'open', 'c': 'close', 
                'h': 'high', 'l': 'low', 't': 'timestamp', 'vw': 'vwap'
            })
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['ticker'] = ticker
            
            target_columns = [
                'ticker', 'timestamp', 'open', 'high', 'low', 'close', 
                'volume', 'vwap', 'pm_high', 'pm_volume', 'gap_percent'
            ]
            
            for col in target_columns:
                if col not in df.columns:
                    df[col] = 0.0
                    
            final_df = df[target_columns]
            
            local_con = con if con else get_db_connection()
            try:
                local_con.register('candles_chunk', final_df)
                local_con.execute("INSERT OR IGNORE INTO historical_data SELECT * FROM candles_chunk")
                
                # Update daily metrics for this chunk
                from .processor import process_daily_metrics
                daily_metrics_df = process_daily_metrics(final_df)
                if not daily_metrics_df.empty:
                    local_con.register('daily_chunk', daily_metrics_df)
                    local_con.execute("INSERT OR REPLACE INTO daily_metrics SELECT * FROM daily_chunk")
            except Exception as e:
                print(f"Chunk DB error for {ticker}: {e}")
            finally:
                if not con:
                    local_con.close()
        
        current_start = current_end + timedelta(days=1)

FALLBACK_TICKERS = [
    "AAPL", "TSLA", "NVDA", "AMD", "META", "MSFT", "GOOGL", "AMZN", "NFLX", "COIN",
    "MARA", "RIOT", "PLTR", "SOFI", "NIO", "INTC", "PYPL", "SQ", "ROKU",
    "BA", "DIS", "T", "F", "GM", "XOM", "CVX", "JPM", "BAC", "WFC"
]

def ingest_ticker_snapshot():
    """Update Tickers master list"""
    client = MassiveClient()
    tickers_data = client.get_tickers()
    
    if not tickers_data:
        print("💡 Using fallback ticker list for MVP (Snapshot restricted on Free Tier).")
        tickers_data = [{"ticker": t} for t in FALLBACK_TICKERS]
    
    df = pd.DataFrame(tickers_data)
    if 'ticker' not in df.columns:
        print("Invalid data from snapshot API.")
        return

    df['name'] = df['ticker']
    df['active'] = True
    # Randomize last_updated to avoid all starting at the exact same sub-second
    df['last_updated'] = [datetime.now() - timedelta(days=365 + i) for i in range(len(df))]
    
    target_df = df[['ticker', 'name', 'active', 'last_updated']]
    con = get_db_connection()
    con.execute("DELETE FROM tickers")
    con.register('df_view', target_df)
    con.execute("INSERT INTO tickers SELECT * FROM df_view")
    con.close()
    print(f"Tickers master list updated ({len(df)} records).")

# Legacy helper, redirected to pulse logic if called manually
def ingest_history(ticker, days=30):
    client = MassiveClient()
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    ingest_ticker_history_range(client, ticker, from_date, to_date)

