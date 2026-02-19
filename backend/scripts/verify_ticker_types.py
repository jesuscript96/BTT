
import duckdb
from app.database import get_db_connection
from app.services.query_service import build_screener_query

def verify_ticker_types():
    con = None
    try:
        con = get_db_connection(read_only=True)
        print("Connected to DB.")
        
        # Build query with no filters (defaults)
        filters = {}
        limit = 100
        rec_query, sql_p, _, _, _, _ = build_screener_query(filters, limit)
        
        print(f"Executing Query:\n{rec_query}\nWith params: {sql_p}")
        
        # Execute
        cur = con.execute(rec_query, sql_p)
        rows = cur.fetchall()
        
        if not rows:
            print("No records found.")
            return

        cols = [d[0] for d in cur.description]
        tickers = [dict(zip(cols, r))['ticker'] for r in rows]
        
        print(f"Retrieved {len(tickers)} tickers. Checking types...")
        
        # Verify types for these tickers
        placeholders = ','.join(['?'] * len(tickers))
        type_query = f"SELECT ticker, type FROM massive.tickers WHERE ticker IN ({placeholders})"
        
        type_rows = con.execute(type_query, tickers).fetchall()
        type_map = {r[0]: r[1] for r in type_rows}
        
        invalid_tickers = []
        valid_types = ['CS', 'ADRC', 'OS']
        
        for t in tickers:
            ttype = type_map.get(t, 'UNKNOWN')
            if ttype not in valid_types:
                invalid_tickers.append((t, ttype))
        
        if invalid_tickers:
            print(f"❌ FAILED: Found {len(invalid_tickers)} invalid tickers:")
            for t, ttype in invalid_tickers:
                print(f"  {t}: {ttype}")
        else:
            print("✅ SUCCESS: All returned tickers are valid types (CS, ADRC, OS).")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        if con: con.close()

if __name__ == "__main__":
    verify_ticker_types()
