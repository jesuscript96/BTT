import os

search_dir = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/frontend/src'
target = 'fetchPrecacheStatus'

print(f"Searching for '{target}' in {search_dir}...")
for root, dirs, files in os.walk(search_dir):
    for f in files:
        if f.endswith(('.tsx', '.ts', '.js', '.jsx')):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8') as file:
                    content = file.read()
                    if target in content:
                        print(f"Found in {path}")
                        lines = content.split('\n')
                        for i, line in enumerate(lines):
                            if target in line:
                                print(f"  Line {i+1}: {line.strip()}")
            except Exception as e:
                pass
