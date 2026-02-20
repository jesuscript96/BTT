import duckdb
import os

def merge_market_data():
    source_db = "backend/market_data_test.duckdb"
    target_db = "backend/market_data.duckdb"
    
    if not os.path.exists(source_db):
        print(f"Source database {source_db} not found.")
        return
    
    # Connect to target (or create if not exists)
    con = duckdb.connect(target_db)
    
    print(f"Merging data from {source_db} into {target_db}...")
    
    # Attach source database
    con.execute(f"ATTACH '{source_db}' AS src")
    
    # Create daily_metrics if not exists (should match schema)
    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_metrics (
            ticker TEXT, 
            timestamp TIMESTAMP, 
            open DOUBLE, 
            high DOUBLE, 
            low DOUBLE, 
            close DOUBLE, 
            volume DOUBLE, 
            vwap DOUBLE, 
            pm_high DOUBLE, 
            pm_low DOUBLE, 
            atr DOUBLE
        )
    """)
    
    # Check if data already exists for these tickers to avoid duplicates
    con.execute("DELETE FROM daily_metrics WHERE ticker IN (SELECT DISTINCT ticker FROM src.daily_metrics)")
    
    # Insert from source
    con.execute("INSERT INTO daily_metrics SELECT * FROM src.daily_metrics")
    
    # Verify count
    count = con.execute("SELECT count(*) FROM daily_metrics").fetchone()[0]
    print(f"Merge complete. Total rows in target: {count}")
    
    con.execute("DETACH src")
    con.close()

if __name__ == "__main__":
    merge_market_data()
