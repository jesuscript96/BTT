import os

search_dir = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT"
terms = ["change vs", "pct_change", "open price", "median", "mean", "after-market", "premarket"]

for root, dirs, files in os.walk(search_dir):
    if ".venv" in root or ".next" in root or "node_modules" in root or ".git" in root:
        continue
    for file in files:
        if file.endswith((".py", ".ts", ".tsx", ".js", ".json")):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                found = []
                for term in terms:
                    if term.lower() in content.lower():
                        found.append(term)
                if found:
                    print(f"File: {path} contains: {found}")
            except Exception as e:
                pass
