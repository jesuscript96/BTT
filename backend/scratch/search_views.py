import os

backend_dir = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'

for root, dirs, files in os.walk(backend_dir):
    # Skip .venv
    if '.venv' in root.split(os.sep):
        continue
    for file in files:
        if file.endswith('.py'):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if 'daily_metrics' in content.lower():
                    lines = content.splitlines()
                    for idx, line in enumerate(lines):
                        if 'create view' in line.lower() and 'daily_metrics' in line.lower():
                            print(f"File: {os.path.relpath(path, backend_dir)} Line {idx+1}: {line}")
                        elif 'daily_metrics' in line.lower() and ('massive' in line.lower() or 'schema' in line.lower()):
                            print(f"File: {os.path.relpath(path, backend_dir)} Line {idx+1}: {line}")
