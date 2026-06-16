import os

search_dir = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/app'
target = 'def load_tickers_cache'

print(f"Searching for '{target}' in {search_dir}...")
for root, dirs, files in os.walk(search_dir):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8') as file:
                    content = file.read()
                    if target in content:
                        print(f"Found in {path}")
            except Exception as e:
                pass
