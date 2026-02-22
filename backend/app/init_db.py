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
    
    tables = cur.execute("SHOW TABLES").fetchall()
    print(f"Current tables in massive: {[t[0] for t in tables]}")

if __name__ == "__main__":
    init_db()
