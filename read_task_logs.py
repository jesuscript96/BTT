import os

log_path = r"C:\Users\Famil\.gemini\antigravity\brain\3608de53-bc05-401b-9ba2-9fa54a6e8378\.system_generated\tasks\task-1029.log"

if os.path.exists(log_path):
    print("Log file exists. Size:", os.path.getsize(log_path))
    with open(log_path, "r", encoding="utf-8") as f:
        print(f.read())
else:
    print("Log file does not exist.")
