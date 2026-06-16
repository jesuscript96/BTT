import os

def search_in_file(path, query):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if query.lower() in line.lower():
                    print(f"{line_num}: {line.strip()}")
    except Exception as e:
        print(f"Error reading {path}: {e}")

search_in_file("backend/app/services/indicators.py", "look_ahead")
print("-" * 40)
search_in_file("backend/app/services/backtest_service.py", "look_ahead")
