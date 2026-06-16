import os

frontend_dir = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\frontend"

for root, dirs, files in os.walk(frontend_dir):
    if ".next" in root or "node_modules" in root:
        continue
    for file in files:
        if file.endswith((".ts", ".js")):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "runBacktestWithDefinition" in content:
                    print(f"Found in {path}")
            except Exception as e:
                pass
