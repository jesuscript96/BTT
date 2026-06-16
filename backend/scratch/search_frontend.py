import os

search_dir = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/frontend/src'
for root, dirs, files in os.walk(search_dir):
    for file in files:
        if file.endswith('.tsx') or file.endswith('.ts'):
            path = os.path.join(root, file)
            if 'node_modules' in path:
                continue
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if 'postgap' in line.lower() or 'precondition' in line.lower():
                    print(f"{path}:{i+1}: {line.strip()}")
