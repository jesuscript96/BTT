import os

# Search frontend files recursively for /backtest or api/backtest
found = []
for root, dirs, files in os.walk(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\frontend\src'):
    for file in files:
        if file.endswith('.tsx') or file.endswith('.ts'):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if '/backtest' in content:
                    found.append(path)

print("Found '/backtest' in:")
for p in found:
    print(f"  {p}")
