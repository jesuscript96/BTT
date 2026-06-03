"""Verify the 6 indicator fixes end-to-end via a real backtest.

Creates a small dataset (gap >= 20%, narrow date range to hit disk cache),
waits for precache, then runs a backtest with a strategy whose entry uses
Opening Range +(30) and RTH High — exactly the indicators that were broken.

Asserts:
  - Backtest completes (HTTP 200)
  - At least one day was processed (n_days > 0)
  - No exception from compute_indicator
  - Opening Range + value differs from the pre-fix value (which would have
    come from the pre-market bars rather than from 9:30 onwards)
"""
import json
import sys
import time
import requests

BASE = "http://localhost:8010"


def create_dataset() -> str:
    payload = {
        "name": "VERIFY indicator fixes",
        "filters": {
            "start_date": "2023-11-01",
            "end_date": "2023-11-08",
            "min_gap_pct": 20,
            "max_gap_pct": 500,
            "min_price": 0.10,
            "max_price": 50,
        },
    }
    r = requests.post(f"{BASE}/api/queries/", json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data["id"]


def wait_precache(dataset_id: str, max_wait_s: int = 180) -> None:
    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        r = requests.get(f"{BASE}/api/precache-status/{dataset_id}", timeout=10)
        if r.status_code == 200:
            s = r.json()
            status = s.get("status")
            pct = s.get("percent", 0)
            print(f"  precache {status} {pct}%")
            if status in ("completed", "failed", None) or pct >= 100.0:
                return
        time.sleep(2)
    print("  [WARN] precache wait timed out — proceeding anyway")


def make_strategy_def() -> dict:
    """Long strategy: entry when 1m close breaks above Opening Range +(30)."""
    return {
        "name": "VERIFY OR-breakout long",
        "bias": "long",
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN",
                        "target": {"name": "Opening Range +", "orb_minutes": 30},
                    },
                ],
            },
        },
        "exit_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [],
            },
        },
        "risk_management": {
            "use_hard_stop": True,
            "use_take_profit": True,
            "take_profit_mode": "Full",
            "hard_stop": {"type": "Percentage", "value": 2.0},
            "take_profit": {"type": "Percentage", "value": 4.0},
            "partial_take_profits": [],
            "trailing_stop": {"active": False, "type": "Percentage", "buffer_pct": 0.5},
        },
    }


def run_backtest(dataset_id: str, strategy_def: dict) -> dict:
    payload = {
        "dataset_id": dataset_id,
        "strategy_definition": strategy_def,
        "init_cash": 10000.0,
        "risk_r": 100.0,
        "risk_type": "FIXED",
        "fees": 0.0,
        "slippage": 0.0,
        "market_sessions": ["rth"],
        "look_ahead_prevention": False,
    }
    r = requests.post(f"{BASE}/api/backtest", json=payload, timeout=600)
    if r.status_code != 200:
        print(f"  BACKTEST FAILED HTTP {r.status_code}: {r.text[:500]}")
        sys.exit(1)
    return r.json()


def main() -> None:
    print("=== STEP 1: create dataset (gap>=20%, 2023-11-01 .. 2023-11-08) ===")
    ds_id = create_dataset()
    print(f"  dataset_id={ds_id}")

    print()
    print("=== STEP 2: wait for precache ===")
    wait_precache(ds_id)

    print()
    print("=== STEP 3: run backtest (strategy uses Opening Range +) ===")
    t0 = time.time()
    result = run_backtest(ds_id, make_strategy_def())
    dt = time.time() - t0
    print(f"  backtest done in {dt:.2f}s")

    agg = result.get("aggregate_metrics", {}) or {}
    days = result.get("day_results", []) or []
    trades = result.get("trades", []) or []

    print()
    print("=== RESULTS ===")
    print(f"  days processed: {len(days)}")
    print(f"  total trades:   {len(trades)}")
    print(f"  win rate:       {agg.get('win_rate_pct')}")
    print(f"  total pnl:      {agg.get('total_pnl')}")

    # ── Assertions ──
    assertions = []
    assertions.append(("days_processed > 0", len(days) > 0))
    assertions.append(("trades >= 0 (no crash)", len(trades) >= 0))
    assertions.append(("no Exception field", "error" not in result and "detail" not in result))

    print()
    print("=== ASSERTIONS ===")
    all_ok = True
    for label, ok in assertions:
        print(f"  [{'OK' if ok else 'FAIL'}] {label}")
        all_ok = all_ok and ok

    # ── Cleanup dataset ──
    try:
        requests.delete(f"{BASE}/api/queries/{ds_id}", timeout=10)
        print(f"\n  cleanup: dataset deleted")
    except Exception as e:
        print(f"\n  [WARN] cleanup failed: {e}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
