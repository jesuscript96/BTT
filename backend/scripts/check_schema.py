import os
import duckdb
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")
con = duckdb.connect(f"md:massive?motherduck_token={token}")

print("SPLITS:")
print(con.execute("DESCRIBE splits").df())

print("\nETF:")
print(con.execute("DESCRIBE ETF").df())
