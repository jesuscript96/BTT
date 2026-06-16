import sys
import os
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.services.cache_service import get_hot_daily_cache

df = get_hot_daily_cache()
print("Hot daily cache shape:", df.shape)
if df is not None and not df.empty:
    print("Gap Pct range in cache:")
    print("Min:", df['gap_pct'].min())
    print("Max:", df['gap_pct'].max())
    print("Mean:", df['gap_pct'].mean())
    print("Number of rows with gap_pct >= 5.0:", len(df[df['gap_pct'] >= 5.0]))
    print("Number of rows with gap_pct >= 10.0:", len(df[df['gap_pct'] >= 10.0]))
else:
    print("Hot cache is empty or None.")
