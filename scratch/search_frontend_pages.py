import os

def list_files(directory):
    for root, dirs, files in os.walk(directory):
        if ".next" in root or "node_modules" in root:
            continue
        for file in files:
            if file.endswith(('.tsx', '.ts')):
                print(os.path.join(root, file))

list_files("./frontend/src")
