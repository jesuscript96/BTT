import os

backend_dir = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'

for root, dirs, files in os.walk(backend_dir):
    for file in files:
        if file.endswith('.py'):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if 'massive' in content.lower():
                    print(f"File: {os.path.relpath(path, backend_dir)} contains 'massive'")
                    # Find exact line
                    lines = content.splitlines()
                    for idx, line in enumerate(lines):
                        if 'massive' in line.lower():
                            print(f"  Line {idx+1}: {line}")
