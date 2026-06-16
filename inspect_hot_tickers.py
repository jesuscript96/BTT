import sys
import os
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.services.cache_service import get_hot_daily_cache

df = get_hot_daily_cache()
print("Hot daily cache shape:", df.shape)
print("Unique tickers count in hot cache:", df['ticker'].nunique())
print("Top 15 tickers by row count in hot cache:")
print(df['ticker'].value_counts().head(15))

# Check some ticker that is likely to have gaps, e.g. MULN or similar if present
print("\nChecking if MULN is in hot cache:")
muln_df = df[df['ticker'] == 'MULN']
print(f"MULN rows: {len(muln_df)}")
if not muln_df.empty:
    print(muln_df[['timestamp', 'gap_pct', 'pm_high', 'rth_open', 'rth_close']].head(5))
