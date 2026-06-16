with open(r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\app\services\data_service.py", "r", encoding="utf-8") as f:
    content = f.read()

import re
match = re.search(r"def fetch_dataset_data\([\s\S]*?^def ", content, re.MULTILINE)
if match:
    print(match.group(0)[:1500])
else:
    print("Not found")
