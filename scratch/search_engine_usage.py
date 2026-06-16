import os
import sys

# Change directory to backend/ so imports work correctly
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

# Search files recursively for "BacktestEngine"
found = []
for root, dirs, files in os.walk('app'):
    for file in files:
        if file.endswith('.py'):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if 'BacktestEngine' in content:
                    found.append(path)

print("Found 'BacktestEngine' in:")
for p in found:
    print(f"  {p}")
