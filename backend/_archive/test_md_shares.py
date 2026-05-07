import os
from dotenv import load_dotenv
import duckdb

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")

try:
    con = duckdb.connect(f"md:?motherduck_token={token}")
    print("Checking databases and shares...")
    bases = con.execute("SELECT * FROM md_information_schema.databases").df()
    print("Databases:\n", bases)
    
    try:
        shares_in = con.execute("SELECT * FROM md_information_schema.shared_with_me").df()
        print("\nShared with me:\n", shares_in)
    except Exception as e:
        print("Could not read shared_with_me:", e)
        
    try:
        shares_out = con.execute("SELECT * FROM md_information_schema.owned_shares").df()
        print("\nOwned shares:\n", shares_out)
    except Exception as e:
        print("Could not read owned_shares:", e)
        
except Exception as e:
    print("❌ Error:", e)
