import duckdb
import os
from dotenv import load_dotenv

load_dotenv('backend/.env')

con = duckdb.connect('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb')

# Let's attach memory DB and load views if GCS is configured, or just show main schema tables/views.
print("Tables/Views:")
print(con.execute("PRAGMA show_tables").fetchall())

print("\nSaved strategies:")
print(con.execute("SELECT id, name FROM strategies").fetchall())

con.close()
