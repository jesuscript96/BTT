import os

backend_path = "c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend"

print("Searching for vwap (case insensitive) in app/services/:")
for root, dirs, files in os.walk(os.path.join(backend_path, "app", "services")):
    for f in files:
        if f.endswith(".py"):
            p = os.path.join(root, f)
            try:
                with open(p, "r", encoding="utf-8") as file:
                    content = file.read()
                    if "vwap" in content.lower():
                        print(f"Found in: {p}")
            except Exception as e:
                pass
