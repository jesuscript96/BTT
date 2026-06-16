import os

path = "app/db/gcs_cache.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

found = False
for idx, line in enumerate(lines):
    if "def _fetch_and_cache_month" in line:
        found = True
        print("".join(lines[idx:idx+100]))
        break
if not found:
    print("_fetch_and_cache_month not found")
