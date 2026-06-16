import re

log_path = r"C:\Users\Famil\.gemini\antigravity\brain\3a371916-4780-44c3-b02c-047213194057\.system_generated\tasks\task-253.log"

try:
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        
    print("--- Searching for dataset ID 181f1faf-c029-45e3-bb17-20ae7ecba79d ---")
    lines = [line for line in content.split("\n") if "181f1faf-c029-45e3-bb17-20ae7ecba79d" in line]
    for line in lines:
        print(line)
        
except Exception as e:
    print("Error:", e)
