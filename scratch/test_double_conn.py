import duckdb

try:
    con1 = duckdb.connect("test_db.duckdb")
    print("Opened con1")
    con2 = duckdb.connect("test_db.duckdb")
    print("Opened con2")
    con1.close()
    con2.close()
except Exception as e:
    print("Error:", e)
