import os
from dotenv import load_dotenv
import duckdb
from uuid import uuid4
from datetime import datetime
import json

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")

try:
    con = duckdb.connect(f"md:massive?motherduck_token={token}")
    print("Testing insert into massive with md:massive...")
    new_id = str(uuid4())
    now = datetime.now()
    try:
        con.execute(
            """
            INSERT INTO strategies (id, name, description, created_at, updated_at, definition)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_id, "test", "test", now, now, json.dumps({}))
        )
        print("✅ Inserted into massive.main.strategies (md:massive connection)")
    except Exception as e:
        print("❌ Error inserting with md:massive:", e)
        
    con2 = duckdb.connect(f"md:?motherduck_token={token}")
    print("\nTesting insert into massive with md: + massive.main.strategies...")
    try:
        con2.execute(
            """
            INSERT INTO massive.main.strategies (id, name, description, created_at, updated_at, definition)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_id, "test2", "test2", now, now, json.dumps({}))
        )
        print("✅ Inserted into massive.main.strategies (md: connection)")
    except Exception as e:
        print("❌ Error inserting with md: + massive.main.strategies:", e)

    con3 = duckdb.connect(f"md:?motherduck_token={token}")
    print("\nTesting insert into massive with md: + USE massive...")
    try:
        con3.execute("USE massive")
        con3.execute(
            """
            INSERT INTO strategies (id, name, description, created_at, updated_at, definition)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_id, "test3", "test3", now, now, json.dumps({}))
        )
        print("✅ Inserted into massive.main.strategies (USE massive)")
    except Exception as e:
        print("❌ Error inserting with USE massive:", e)

except Exception as e:
    print("❌ Critical Error:", e)
