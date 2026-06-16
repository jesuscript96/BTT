with open('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/frontend/src/components/backtester/BacktestPanel.tsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'precacheStatus' in line or 'precache_status' in line:
        print(f"Line {i+1}: {line.strip()}")
