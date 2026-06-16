import os

term = "entry_time_windows"
search_path = "c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/frontend"
for root, dirs, files in os.walk(search_path):
    if "node_modules" in root or ".next" in root or ".git" in root:
        continue
    for file in files:
        if file.endswith((".ts", ".tsx", ".js", ".jsx")):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                for idx, line in enumerate(lines):
                    if term in line:
                        print(f"{path}:{idx+1}: {line.strip()}")
