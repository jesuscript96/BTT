with open('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/app/services/indicators.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if '_ticker_daily_ohlc_cache' in line:
        print(f"Line {idx+1}: {line.strip()}")
