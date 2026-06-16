import os
import re

search_terms = [r"Market Structure", r"HOD/LOD", r"HOD", r"LOD", r"market_structure"]
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
                for term in search_terms:
                    matches = re.findall(term, content, re.IGNORECASE)
                    if matches:
                        print(f"Found '{term}' in {path} ({len(matches)} matches)")
            except Exception as e:
                pass
