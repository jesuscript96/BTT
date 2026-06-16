import os

log_path = r"C:\Users\Famil\.gemini\antigravity\brain\046173e2-46fa-4293-a559-5e20c48574d6\.system_generated\tasks\task-2241.log"
print(f"Reading log: {log_path}")
try:
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    found = False
    for idx, line in enumerate(lines):
        if "entry_time_windows" in line:
            print(f"[{idx}] {line.strip()}")
            found = True
            
    if not found:
        print("No matches for 'entry_time_windows' in the uvicorn log.")
            
except Exception as e:
    print("Error:", e)
