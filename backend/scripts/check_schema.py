import duckdb
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path="/Users/jvch/Desktop/AutomatoWebs/BTT/backend/.env")

def check_schema():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        print("Error: MOTHERDUCK_TOKEN not found.")
        return

    print("Connecting to MotherDuck...")
    con = duckdb.connect(f"md:massive?motherduck_token={token}")
    
    try:
        # Describe table
        result = con.execute("DESCRIBE daily_metrics").fetchall()
        print("\nSchema for daily_metrics:")
        for row in result:
            print(f"  {row[0]} ({row[1]})")
            
    except Exception as e:
        print(f"Error describing table: {e}")
    finally:
        con.close()

if __name__ == "__main__":
    check_schema()
