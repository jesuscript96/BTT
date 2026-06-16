import os
import json

log_path = r"C:\Users\Famil\.gemini\antigravity\brain\046173e2-46fa-4293-a559-5e20c48574d6\.system_generated\tasks\task-2241.log"
print(f"Reading log: {log_path}")
try:
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    # Let's search for lines containing "BACKTEST START"
    count = 0
    for idx, line in enumerate(lines):
        if "BACKTEST START" in line:
            print(f"[{idx}] {line.strip()}")
            count += 1
            # print surrounding lines
            start_idx = max(0, idx - 2)
            end_idx = min(len(lines), idx + 5)
            print("Surrounding lines:")
            for j in range(start_idx, end_idx):
                print(f"  {j}: {lines[j].strip()}")
            print("-" * 50)
            
except Exception as e:
    print("Error:", e)
