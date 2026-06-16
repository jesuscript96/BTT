import os
import re

backend_dir = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend"

print("Detailed search in main backend files...")

files_to_check = [
    os.path.join(backend_dir, "app", "backtester", "engine.py"),
    os.path.join(backend_dir, "app", "services", "indicators.py"),
    os.path.join(backend_dir, "app", "services", "strategy_engine.py"),
    os.path.join(backend_dir, "app", "services", "backtest_service.py"),
    os.path.join(backend_dir, "app", "services", "data_service.py"),
]

patterns = [
    re.compile(r"hour", re.IGNORECASE),
    re.compile(r"time", re.IGNORECASE),
    re.compile(r"session", re.IGNORECASE),
    re.compile(r"\b[0-9]{1,2}:[0-9]{2}\b"),
]

for path in files_to_check:
    if not os.path.exists(path):
        print(f"File not found: {path}")
        continue
    print(f"\n--- {os.path.basename(path)} ---")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for idx, line in enumerate(lines):
        # We want to print lines that look like they perform time checks or filters
        # e.g., hour comparison, dt.time, timestamp comparisons, session filtering, or have hours 7/9
        line_lower = line.lower()
        if any(p.search(line) for p in patterns):
            # narrow down to actual logic
            if any(term in line_lower for term in [
                "filter", "session", "rth", "pm", "am", "between", "hour", "minute", "time_window",
                "07:", "09:", "7:", "9:", "7", "9", "start", "end", "close", "open"
            ]):
                # print it
                print(f"L{idx+1}: {line.strip()}")
