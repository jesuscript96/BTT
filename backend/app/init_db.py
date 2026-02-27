from app.database import get_db_connection

def init_db():
    """Create strategies and saved_queries tables if they do not exist."""
    cur = get_db_connection()
    print("Checking and creating tables in massive...")
    
    # 1. Saved Queries (Datasets)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_queries (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            filters VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("- Verified table: saved_queries")

    # 2. Strategies
    cur.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            description VARCHAR,
            definition VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("- Verified table: strategies")

    # 3. Datasets (New structure for persistence)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS datasets (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("- Verified table: datasets")

    # 4. Dataset Pairs (Combination of Ticker and Date)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dataset_pairs (
            dataset_id VARCHAR NOT NULL,
            ticker VARCHAR NOT NULL,
            date DATE NOT NULL,
            PRIMARY KEY (dataset_id, ticker, date)
        )
    """)
    print("- Verified table: dataset_pairs")
    
    tables = cur.execute("SHOW TABLES").fetchall()
    print(f"Current tables in massive: {[t[0] for t in tables]}")

if __name__ == "__main__":
    init_db()
