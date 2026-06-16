import os

def search_files(directory, query):
    results = []
    for root, dirs, files in os.walk(directory):
        if ".git" in root or ".venv" in root or "__pycache__" in root or "node_modules" in root or ".next" in root:
            continue
        for file in files:
            if file.endswith((".ts", ".tsx", ".js", ".jsx", ".json")):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        for line_num, line in enumerate(f, 1):
                            if query in line:
                                results.append((path, line_num, line.strip()))
                except Exception:
                    pass
    return results

print("Searching frontend for 'progress'...")
res = search_files("./frontend", "progress")
for r in res[:40]:
    print(f"{r[0]}:{r[1]} - {r[2]}")
