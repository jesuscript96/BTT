with open(r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\app\services\portfolio_sim.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if any(term in line for term in ["Market Structure", "HOD", "LOD", "hard_stop"]):
        print(f"portfolio_sim.py:{i+1}: {line.strip()}")

print("\n--- backtest_service.py ---")
with open(r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\app\services\backtest_service.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if any(term in line for term in ["Market Structure", "HOD", "LOD", "hard_stop"]):
        print(f"backtest_service.py:{i+1}: {line.strip()}")
