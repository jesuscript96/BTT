import os

path = "app/db/gcs_cache.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

print("".join(lines[747:850]))
