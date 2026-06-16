import os

log_path = r"C:\Users\Famil\.gemini\antigravity\brain\046173e2-46fa-4293-a559-5e20c48574d6\.system_generated\tasks\task-3890.log"
print(f"Checking if log exists at {log_path}:")
if os.path.exists(log_path):
    print("Log exists!")
    with open(log_path, "r", encoding="utf-8") as f:
        print(f.read())
else:
    print("Log does NOT exist yet.")
