with open('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/frontend/src/components/backtester/BacktestPanel.tsx', 'r', encoding='utf-8') as f:
    for idx, line in enumerate(f, 1):
        line_lower = line.lower()
        if 'inlinedatasetbuilder' in line_lower or 'dataset' in line_lower:
            # only print lines that have build, save, or select
            if any(w in line_lower for w in ('build', 'save', 'select', 'load', 'create')):
                print(f"{idx}: {line.strip()}")
