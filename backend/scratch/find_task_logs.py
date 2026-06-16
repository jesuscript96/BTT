import os
import glob

search_dir = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume"
print(f"Searching for .log files in {search_dir}:")
pattern = os.path.join(search_dir, "**", "*.log")
log_files = glob.glob(pattern, recursive=True)
for lf in sorted(log_files):
    # Skip .venv folder logs
    if ".venv" in lf:
        continue
    print(f"Found: {lf} (size: {os.path.getsize(lf)} bytes)")
