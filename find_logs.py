import os

search_dir = r"C:\Users\Famil\.gemini\antigravity"

print("Searching for task-1029.log or similar task logs:")
for root, dirs, files in os.walk(search_dir):
    for f in files:
        if "task-1029" in f or "task-1002" in f:
            print(os.path.join(root, f))
