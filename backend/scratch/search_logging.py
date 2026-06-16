import os

backend_dir = "c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend"
for root, dirs, files in os.walk(backend_dir):
    for f in files:
        if f.endswith(".py") or f.endswith(".json") or f.endswith(".ini"):
            filepath = os.path.join(root, f)
            try:
                with open(filepath, "r", encoding="utf-8") as file:
                    content = file.read()
                    if "logging.config" in content or "basicConfig" in content or "setLevel" in content or "logger = logging.getLogger" in content:
                        # Find occurrences of setLevel
                        lines = content.split("\n")
                        for i, line in enumerate(lines, 1):
                            if "setLevel" in line or "basicConfig" in line:
                                print(f"{f}:{i}: {line.strip()}")
            except Exception:
                pass
