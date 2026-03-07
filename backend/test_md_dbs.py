import os
from dotenv import load_dotenv
import duckdb

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")

try:
    con = duckdb.connect(f"md:?motherduck_token={token}")
    bases = con.execute("SHOW DATABASES").fetchall()
    for b in bases:
        db_name = b[0]
        print(f"\n- Database: {db_name}")
        try:
            con.execute(f"USE {db_name}")
            tables = con.execute("SHOW TABLES").fetchall()
            table_names = [t[0] for t in tables]
            print(f"  Tables: {table_names}")
            if "saved_queries" in table_names:
                count = con.execute(f"SELECT count(*) FROM saved_queries").fetchone()[0]
                print(f"  -> has {count} saved_queries")
        except Exception as e:
            print(f"  Error reading tables: {e}")
except Exception as e:
    print("❌ Error:", e)
