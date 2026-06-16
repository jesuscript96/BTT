import os

def search_files(directory, query):
    results = []
    for root, dirs, files in os.walk(directory):
        if ".git" in root or ".venv" in root or "__pycache__" in root or ".agent" in root:
            continue
        for file in files:
            if file.endswith((".py", ".json", ".md", ".ts", ".tsx", ".js")):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        for line_num, line in enumerate(f, 1):
                            if query in line:
                                results.append((path, line_num, line.strip()))
                except Exception:
                    pass
    return results

query = "Previous max"
print(f"Searching for '{query}'...")
res = search_files(".", query)
print(f"Found {len(res)} occurrences:")
for r in res[:50]:
    print(f"{r[0]}:{r[1]} - {r[2]}")
