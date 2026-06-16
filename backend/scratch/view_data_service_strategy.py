import os

path = "app/services/data_service.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if "def get_strategy" in line:
        print("".join(lines[idx:idx+30]))
        break
