with open('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/app/services/strategy_engine.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if 'trailing' in line.lower() or 'trail' in line.lower():
        print(f"Line {idx+1}: {line.strip()}")
