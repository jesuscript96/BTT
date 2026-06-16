import os
import re

backend_dir = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend"

for root, dirs, files in os.walk(backend_dir):
    if ".git" in root or "__pycache__" in root or ".venv" in root:
        continue
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "def fetch_intraday_batch" in content:
                    print(f"Found function in {path}:")
                    match = re.search(r"def fetch_intraday_batch\([\s\S]*?^def ", content, re.MULTILINE)
                    if match:
                        print(match.group(0)[:1500])
                    else:
                        print("Context too long or no other def")
            except Exception as e:
                pass
