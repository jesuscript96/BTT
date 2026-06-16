import os
import re

backend_dir = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend"

print("Searching for time-related constraints/filters in the Python codebase...")

patterns = [
    re.compile(r"\bhour\b", re.IGNORECASE),
    re.compile(r"\btime\b", re.IGNORECASE),
    re.compile(r"07\b"),
    re.compile(r"09\b"),
    re.compile(r"\b7\s*:\s*00", re.IGNORECASE),
    re.compile(r"\b9\s*:\s*00", re.IGNORECASE),
    re.compile(r"session", re.IGNORECASE),
    re.compile(r"market_session", re.IGNORECASE)
]

for root, dirs, files in os.walk(backend_dir):
    if ".venv" in root or "__pycache__" in root or ".git" in root or ".cache" in root:
        continue
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for idx, line in enumerate(lines):
                    # Check if line contains any interesting patterns
                    # Let's check specifically for hour/time filtering or hardcoded times
                    if any(p.search(line) for p in patterns):
                        # print context
                        # We want to filter for things like:
                        # - comparisons with 7 or 9
                        # - comments about 7 or 9 or premarket
                        # - session limits
                        low = line.lower()
                        if "7" in low or "9" in low or "session" in low or "filter" in low or "window" in low or "time" in low:
                            # print line if it seems like a condition or time limit
                            if any(x in low for x in [">", "<", "==", "between", "hour", "minute", "timestamp", "session", "dt.", "time_"]):
                                print(f"{os.path.relpath(path, backend_dir)}:{idx+1}: {line.strip()}")
            except Exception as e:
                pass
