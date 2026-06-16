import os

def search_text(directory, term):
    results = []
    for root, dirs, files in os.walk(directory):
        if ".git" in root or "node_modules" in root or ".next" in root or ".venv" in root:
            continue
        for file in files:
            if file.endswith(('.tsx', '.ts', '.py')):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        for line_num, line in enumerate(f, 1):
                            if term.lower() in line.lower():
                                results.append((path, line_num, line.strip()))
                except Exception:
                    pass
    return results

terms = ["MIN PM GAP", "MAX PM GAP", "market & summary", "screener", "scan", "MIN_PM_GAP", "MAX_PM_GAP"]
for t in terms:
    print(f"\n=== Search for '{t}' ===")
    for r in search_text("./frontend/src", t)[:10]:
        print(f"{r[0]}:{r[1]}: {r[2]}")
