import os

backend_path = "c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend"

print("Searching for daily_metrics or intraday_1m in python files:")
for root, dirs, files in os.walk(backend_path):
    for f in files:
        if f.endswith(".py"):
            p = os.path.join(root, f)
            try:
                with open(p, "r", encoding="utf-8") as file:
                    content = file.read()
                    if "daily_metrics" in content or "intraday_1m" in content:
                        print(f"Found in: {p}")
            except Exception as e:
                pass
