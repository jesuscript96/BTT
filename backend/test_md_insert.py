import os
from dotenv import load_dotenv
import duckdb

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")

try:
    con = duckdb.connect(f"md:?motherduck_token={token}")
    print("Testing insert into massive.main.strategies...")
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS massive.main.test_table (
            id INTEGER,
            name VARCHAR
        )
    """)
    print("Created test_table")
    
    con.execute("INSERT INTO massive.main.test_table VALUES (1, 'test')")
    print("Inserted into test_table")
    
    res = con.execute("SELECT * FROM massive.main.test_table").fetchall()
    print("Select:", res)
    
except Exception as e:
    print("❌ Error:", e)
