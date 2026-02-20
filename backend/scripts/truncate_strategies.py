
from app.database import get_db_connection

def truncate_strategies():
    print("Connecting to database...")
    con = get_db_connection()
    print("Truncating strategies table...")
    try:
        con.execute("DELETE FROM strategies")
        print("Strategies table truncated successfully.")
    except Exception as e:
        print(f"Error truncating table: {e}")

if __name__ == "__main__":
    truncate_strategies()
