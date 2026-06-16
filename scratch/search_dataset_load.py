import os

frontend_dir = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\frontend\src"

print("Searching for dataset loading UI components...")

for root, dirs, files in os.walk(frontend_dir):
    for file in files:
        if file.endswith(".tsx"):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if "dataset" in content.lower():
                # print matches
                lines = content.splitlines()
                for idx, line in enumerate(lines):
                    if "saved" in line.lower() or "load" in line.lower() or "select" in line.lower() or "dropdown" in line.lower() or "get" in line.lower():
                        if "dataset" in line.lower():
                            print(f"{os.path.relpath(path, frontend_dir)}:{idx+1}: {line.strip()}")
