import os

log_path = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\scratch\sig_run.log"
if os.path.exists(log_path):
    try:
        with open(log_path, "r", encoding="utf-16") as f:
            content = f.read()
        print("--- SIG RUN LOG CONTENT ---")
        print(content)
        print("---------------------------")
    except Exception as e:
        print(f"Error reading UTF-16 log: {e}")
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                print(f.read())
        except Exception as e2:
            print(f"Error reading UTF-8 log: {e2}")
else:
    print("scratch/sig_run.log does not exist.")
