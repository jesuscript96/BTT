content = open('backend/app/services/indicators.py', encoding='utf-8').read()
print("_safe_float defined:", "_safe_float" in content)
if "_safe_float" in content:
    # Print the lines around _safe_float definition
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if "def _safe_float" in line:
            for j in range(max(0, idx-2), min(len(lines), idx+10)):
                print(f"{j+1}: {lines[j]}")
