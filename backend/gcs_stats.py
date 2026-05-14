from app.database import get_db_connection
import sys

con = get_db_connection()

print("Cargando daily_metrics...")
df = con.execute("""
    SELECT ticker, timestamp, gap_pct, open, close, high, low, volume,
           pm_volume, pm_high, rth_run_pct, day_return_pct
    FROM daily_metrics
""").fetchdf()

print(f"Filas: {len(df):,}")
print(f"Columnas: {len(df.columns)}")
mem_bytes = df.memory_usage(deep=True).sum()
print(f"Memoria total: {mem_bytes / 1024 / 1024:.1f} MB")

# Breakdown
for col in df.columns:
    mb = df[col].memory_usage(deep=True) / 1024 / 1024
    print(f"  {col}: {mb:.1f} MB ({df[col].dtype})")

print()
print("--- float32 downcast ---")
for col in df.select_dtypes(include=['float64']).columns:
    before = df[col].memory_usage(deep=True) / 1024 / 1024
    df[col] = df[col].astype('float32')
    after = df[col].memory_usage(deep=True) / 1024 / 1024
    print(f"  {col}: {before:.1f} -> {after:.1f} MB")

mem_after = df.memory_usage(deep=True).sum()
print(f"\nMemoria despues de float32: {mem_after / 1024 / 1024:.1f} MB")

con.close()
