import duckdb
import pandas as pd

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb'
con = duckdb.connect(db_path, read_only=True)

print("Fetching dataset pairs...")
df = con.execute("SELECT ticker, date FROM dataset_pairs WHERE dataset_id = '78c15895-aaed-4e44-920e-19ba17c64f07'").fetchdf()
print(f"Total pairs fetched: {len(df)}")
if not df.empty:
    df['date'] = pd.to_datetime(df['date'])
    print("\nDate range:")
    print(f"Min date: {df['date'].min()}")
    print(f"Max date: {df['date'].max()}")
    
    print("\nUnique tickers count:", df['ticker'].nunique())
    print("\nSample pairs:")
    print(df.head(10))
    
    print("\nGrouped by year and month:")
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month
    print(df.groupby(['year', 'month']).size())

con.close()
