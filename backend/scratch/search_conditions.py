import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

path = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\frontend\src\components\strategy-builder\ConditionBuilder.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

print(f"File size: {len(content)} chars")
# Find references to distance, comparison, etc.
keywords = ["distancia", "distancia %", "comparacion", "comparación", "VWAP", "Bar Close", "type", "condition"]
for kw in keywords:
    matches = [m.start() for m in re.finditer(kw, content, re.IGNORECASE)]
    print(f"Keyword '{kw}': {len(matches)} matches")

# Let's search for occurrences of 'VWAP' and see the context
lines = content.splitlines()
print("\n--- Sample lines containing VWAP or distance ---")
for idx, line in enumerate(lines):
    if "vwap" in line.lower() or "dist" in line.lower() or "compar" in line.lower():
        print(f"Line {idx+1}: {line.strip()[:120]}")
        # Only print first 20 matches to keep output size readable
        if idx > 200:
            print("... and more")
            break
