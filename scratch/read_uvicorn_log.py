import os

log_path = r"C:\Users\Famil\.gemini\antigravity\brain\046173e2-46fa-4293-a559-5e20c48574d6\.system_generated\tasks\task-2241.log"
print(f"Reading log: {log_path}")
try:
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    print(f"Total lines: {len(lines)}")
    print("\nLast 200 lines:")
    for line in lines[-200:]:
        print(line.rstrip())
except Exception as e:
    print("Error:", e)
