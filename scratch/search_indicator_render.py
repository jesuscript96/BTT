import sys
sys.stdout.reconfigure(encoding='utf-8')

file_path = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\frontend\src\components\strategy-builder\ConditionBuilder.tsx"

print("Searching for select dropdowns or option rendering in ConditionBuilder.tsx...")

with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if "select" in line.lower() or "option" in line.lower() or "indicator" in line.lower():
        if any(term in line.lower() for term in ["map", "list", "dropdown", "source", "target"]):
            print(f"{idx+1}: {line.strip()}")
