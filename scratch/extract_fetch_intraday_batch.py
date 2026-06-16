with open(r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\app\db\gcs_cache.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

start_idx = -1
for idx, line in enumerate(lines):
    if "def fetch_intraday_batch" in line:
        start_idx = idx
        break

if start_idx != -1:
    print(f"Function starts at line {start_idx + 1}")
    for idx, line in enumerate(lines[start_idx:start_idx+120]):
        print(f"{start_idx + idx + 1}: {line}", end="")
else:
    print("Not found")
