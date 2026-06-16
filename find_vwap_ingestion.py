import os

ingestion_path = "c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/app/ingestion.py"

if os.path.exists(ingestion_path):
    print("ingestion.py exists.")
    with open(ingestion_path, "r", encoding="utf-8") as f:
        content = f.read()
        print("References to vwap in ingestion.py:")
        lines = content.split("\n")
        for i, l in enumerate(lines):
            if "vwap" in l.lower():
                print(f"  Line {i+1}: {l}")
else:
    print("ingestion.py does not exist.")
