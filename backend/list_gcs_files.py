from app.database import get_db_connection

con = get_db_connection()
try:
    print("Listing all optimized files...")
    df_opt = con.execute("SELECT file FROM glob('gs://strategybuilderbbdd/cold_storage/intraday_1m_optimized/*/*/*.parquet')").fetchdf()
    for f in sorted(df_opt["file"].tolist()):
        print(f)
        
    print("\nListing all raw files...")
    df_raw = con.execute("SELECT file FROM glob('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet')").fetchdf()
    for f in sorted(df_raw["file"].tolist()):
        print(f)
except Exception as e:
    print("Error:", e)
