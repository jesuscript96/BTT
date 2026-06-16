from app.database import get_db_connection

con = get_db_connection()
try:
    res = con.execute("SELECT * FROM glob('gs://strategybuilderbbdd/cold_storage/intraday_1m_optimized/**/*.parquet')").fetchall()
    years = sorted(list(set([r[0].split('year=')[1].split('/')[0] for r in res])))
    print("Years in optimized folder:", years)
    print("Files in optimized folder:")
    for r in sorted(res):
        print(r[0])
except Exception as e:
    print("Error:", e)
