filepath = r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\frontend\src\components\TickerAnalysis.tsx'
with open(filepath, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        if 'export default' in line or 'function TickerAnalysis' in line:
            print(f"Line {i}: {line.strip()}")
