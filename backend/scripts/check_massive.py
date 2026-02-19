
import duckdb
from app.database import get_db_connection

def check_massive_schema():
    try:
        con = get_db_connection()
        print("Connected to DB.")
        
        # Check if 'massive' schema exists
        schemas = con.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
        print("Schemas:", [s[0] for s in schemas])
        
        # Check tables in massive
        tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='massive'").fetchall()
        print("Tables in massive:", [t[0] for t in tables])
        
        # Check columns in massive.tickers
        columns = con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='massive' AND table_name='tickers'").fetchall()
        print("Columns in massive.tickers:", columns)
        
        # Check some distinct types
        types = con.execute("SELECT DISTINCT type FROM massive.tickers LIMIT 20").fetchall()
        print("Distinct Types:", [t[0] for t in types])
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if con: con.close()

if __name__ == "__main__":
    check_massive_schema()
