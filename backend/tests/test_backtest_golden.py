"""
GOLDEN TEST B — Full backtest result golden (F0 + F1 guard).

Purpose
-------
Locks the OUTPUT of representative backtests so F0 (DuckDB memory_limit /
spill) and F1 (conditional + ticker-pruned prefetch) cannot silently change
results. Captures ``aggregate_metrics`` + the first 100 trades of each
configured backtest and compares against a committed golden with tolerance 0.

Why it runs on the SERVER, not locally
---------------------------------------
The qualifying/intraday caches and the dataset definitions live on the prod
disk; a representative gap-dataset backtest needs them. Run it inside the prod
container (DB_PROVIDER=gcs already set there).

HOW TO RUN (Adrian, on the server)
----------------------------------
1) Pick 2 representative *gap* datasets that are already cached (fast + safe;
   NOT the BROAD datasets). Get their dataset_id and a strategy_id (or paste a
   strategy_definition). For at least ONE case, choose a strategy that uses
   "High of last X days" / "Low of last X days" so F1's prefetch path is
   actually exercised.

2) Create the config (next to this file):
     backend/tests/fixtures/golden_b_config.json
   using the template printed by:
     python tests/test_backtest_golden.py --template

   Shape:
     {
       "cases": [
         {"name": "gap_case_lookback",
          "request": {"dataset_id": "<id>", "strategy_id": "<sid>"}},
         {"name": "gap_case_simple",
          "request": {"dataset_id": "<id>", "strategy_definition": { ... }}}
       ]
     }
   (request accepts any BacktestRequest field: init_cash, risk_r, fees,
   market_sessions, start_date, end_date, ...)

3) CAPTURE the golden on the CURRENT (pre-merge) code — this branch is perf/f0-f1,
   which already contains F0+F1, so capture and then re-run to confirm stability;
   ideally also capture once on `develop` and diff. From the container:
     /opt/venv/bin/python tests/test_backtest_golden.py
   First run writes backend/tests/fixtures/golden_<name>.json and prints CAPTURED.

4) VERIFY: run it again — it must print MATCHED (tolerance 0) for every case.
   To prove F0+F1 didn't move results, capture goldens on `develop` first, then
   checkout perf/f0-f1 and run this test: every case must MATCH.

     # on develop (baseline):  /opt/venv/bin/python tests/test_backtest_golden.py
     # on perf/f0-f1:          /opt/venv/bin/python tests/test_backtest_golden.py
     #   -> all cases MATCHED  => F0+F1 are result-neutral.

Commit the generated golden_<name>.json + golden_b_config.json so the guard is
reproducible.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ on path

try:
    import pytest  # noqa: F401 — only needed under pytest
except ImportError:
    pytest = None

FIX_DIR = Path(__file__).parent / "fixtures"
CONFIG = FIX_DIR / "golden_b_config.json"

CONFIG_TEMPLATE = {
    "cases": [
        {
            "name": "gap_case_lookback",
            "request": {
                "dataset_id": "REPLACE_WITH_CACHED_GAP_DATASET_ID",
                "strategy_id": "REPLACE_WITH_STRATEGY_ID_USING_High_of_last_X_days",
            },
        },
        {
            "name": "gap_case_simple",
            "request": {
                "dataset_id": "REPLACE_WITH_CACHED_GAP_DATASET_ID_2",
                "strategy_id": "REPLACE_WITH_ANY_STRATEGY_ID",
            },
        },
    ]
}


def _sanitize(obj):
    """JSON-safe, deterministic representation. NaN/Inf -> None."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    return obj


def _deep_eq(a, b, path=""):
    """Tolerance-0 deep equality. Returns list of difference descriptions."""
    diffs = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                diffs.append(f"{path}.{k}: missing in current")
            elif k not in b:
                diffs.append(f"{path}.{k}: missing in golden")
            else:
                diffs += _deep_eq(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: len {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diffs += _deep_eq(x, y, f"{path}[{i}]")
    else:
        if a != b:
            diffs.append(f"{path}: {a!r} != {b!r}")
    return diffs


def _capture(case) -> dict:
    from app.services.backtest_orchestrator import BacktestRequest, run_backtest_orchestrator

    req = BacktestRequest(**case["request"])
    result = run_backtest_orchestrator(req)
    trades = result.get("trades", []) or []
    return _sanitize({
        "aggregate_metrics": result.get("aggregate_metrics", {}),
        "n_trades_total": len(trades),
        "trades_first_100": trades[:100],
    })


def _run_case(case) -> tuple[str, list[str]]:
    name = case["name"]
    golden_path = FIX_DIR / f"golden_{name}.json"
    current = _capture(case)
    if not golden_path.exists():
        golden_path.write_text(json.dumps(current, indent=2, sort_keys=True))
        return ("CAPTURED", [])
    golden = json.loads(golden_path.read_text())
    return ("MATCHED" if not _deep_eq(current, golden) else "DIFFERS",
            _deep_eq(current, golden))


def test_backtest_golden():
    assert CONFIG.exists(), (
        f"Missing {CONFIG}. Create it from the template:\n"
        f"  python tests/test_backtest_golden.py --template"
    )
    cfg = json.loads(CONFIG.read_text())
    cases = cfg.get("cases", [])
    assert cases, "golden_b_config.json has no cases"

    all_diffs = []
    for case in cases:
        status, diffs = _run_case(case)
        print(f"[GOLDEN-B] {case['name']}: {status}")
        for d in diffs[:20]:
            print(f"    {d}")
        if status == "DIFFERS":
            all_diffs.append(case["name"])

    assert not all_diffs, (
        f"F0/F1 changed backtest results for: {all_diffs} (must be tolerance 0). "
        f"See diffs above; revert the offending fix."
    )


if __name__ == "__main__":
    if "--template" in sys.argv:
        FIX_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG.exists():
            print(f"{CONFIG} already exists — not overwriting.")
        else:
            CONFIG.write_text(json.dumps(CONFIG_TEMPLATE, indent=2))
            print(f"Wrote template: {CONFIG}\nEdit it with real dataset_id/strategy_id, then re-run.")
    else:
        test_backtest_golden()
        print("OK")
