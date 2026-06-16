import os

with open("app/services/data_service.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

found = False
for idx, line in enumerate(lines):
    if "def iter_intraday_groups_streamed" in line:
        found = True
        print("".join(lines[idx:idx+100]))
        break
if not found:
    print("iter_intraday_groups_streamed not found")
