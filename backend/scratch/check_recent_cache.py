import os
import glob

cache_dir = "c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.cache/intraday"
files = glob.glob(os.path.join(cache_dir, "*.parquet"))
files.sort(key=os.path.getmtime, reverse=True)

print("Recent cache files:")
for f in files[:5]:
    mtime = os.path.getmtime(f)
    import datetime
    dt = datetime.datetime.fromtimestamp(mtime)
    print(f"{os.path.basename(f)}: {os.path.getsize(f)} bytes, modified {dt}")
