import os

def search_text(directory, term):
    results = []
    for root, dirs, files in os.walk(directory):
        if ".git" in root or "node_modules" in root or ".next" in root or ".venv" in root:
            continue
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        for line_num, line in enumerate(f, 1):
                            if term.lower() in line.lower():
                                results.append((path, line_num, line.strip()))
                except Exception:
                    pass
    return results

print("=== Search for pmh_gap_pct in backend ===")
for r in search_text("./backend", "pmh_gap_pct"):
    print(f"{r[0]}:{r[1]}: {r[2]}")
