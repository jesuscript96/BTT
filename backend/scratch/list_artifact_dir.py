import os

brain_dir = r"C:\Users\Famil\.gemini\antigravity\brain\046173e2-46fa-4293-a559-5e20c48574d6"
print(f"Listing all files in {brain_dir}:")
for root, dirs, files in os.walk(brain_dir):
    for f in files:
        full_path = os.path.join(root, f)
        print(f"Found: {full_path} (size: {os.path.getsize(full_path)} bytes)")
