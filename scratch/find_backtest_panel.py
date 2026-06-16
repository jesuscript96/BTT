import os

frontend_dir = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\frontend"
found = []

for root, dirs, files in os.walk(frontend_dir):
    if ".next" in root or "node_modules" in root:
        continue
    for file in files:
        if file.lower() == "backtestpanel.tsx":
            found.append(os.path.join(root, file))

print("Found files:", found)
