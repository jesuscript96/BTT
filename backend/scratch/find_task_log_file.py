import os

base_dir = r"C:\Users\Famil\.gemini\antigravity\brain\046173e2-46fa-4293-a559-5e20c48574d6"
print(f"Walking {base_dir} to search for task-3855:")
found = False
for root, dirs, files in os.walk(base_dir):
    for f in files:
        if "task-3855" in f:
            print(os.path.join(root, f))
            found = True
if not found:
    print("No file with name task-3855 found.")
