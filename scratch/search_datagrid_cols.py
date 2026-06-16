import os

def search_text(path, term):
    results = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                if term.lower() in line.lower():
                    results.append((line_num, line.strip()))
    except Exception as e:
        print(f"Error reading {path}: {e}")
    return results

path = "./frontend/src/components/DataGrid.tsx"
print("=== Columns or PM in DataGrid ===")
for r in search_text(path, "pm")[:30]:
    print(f"{r[0]}: {r[1]}")
