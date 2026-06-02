"""Smoke test: POST /api/strategies/ with the new IndicatorType enum.
Tests new frontend names, legacy aliases, and an intentional invalid name.
"""
import json
import sys

import requests

BASE = "http://localhost:8010"


def make_strategy(name: str, src_indicator: str, tgt_indicator: str = None, value: float = 100.0) -> dict:
    """Build a minimal strategy with one entry condition: src <indicator> > tgt (or value)."""
    if tgt_indicator:
        target = {"name": tgt_indicator}
    else:
        target = value
    return {
        "name": name,
        "description": f"smoke test for {src_indicator}",
        "bias": "long",
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": src_indicator},
                        "comparator": "GREATER_THAN",
                        "target": target,
                    }
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
            "take_profit": {"type": "Percentage", "value": 6.0},
            "partial_take_profits": [],
            "trailing_stop": {"active": False, "type": "Percentage", "buffer_pct": 0.5},
        },
    }


def post(strategy: dict) -> tuple[int, dict | str]:
    r = requests.post(f"{BASE}/api/strategies/", json=strategy, timeout=10)
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


def case(label: str, src: str, expect_status: int, expect_indicator_stored: str | None = None, tgt: str = None):
    status, body = post(make_strategy(f"SMOKE {label}", src, tgt_indicator=tgt))
    ok = status == expect_status
    print(f"  [{'OK' if ok else 'FAIL'}] {label:55s} -> HTTP {status}", end="")
    if ok and expect_status == 200 and expect_indicator_stored:
        stored = body["entry_logic"]["root_condition"]["conditions"][0]["source"]["name"]
        match = stored == expect_indicator_stored
        print(f"  stored={stored!r}  {'OK' if match else f'EXPECTED={expect_indicator_stored!r}'}")
        return ok and match
    elif ok and expect_status != 200:
        # Extract field errors
        errs = body.get("detail", []) if isinstance(body, dict) else body
        print(f"  detail={str(errs)[:120]}")
    else:
        print(f"  body={str(body)[:200]}")
    return ok


print("=== NEW FRONTEND NAMES (should 200) ===")
results = []
results.append(case("PM High",                       "PM High",                       200, "PM High"))
results.append(case("PM Low",                        "PM Low",                        200, "PM Low"))
results.append(case("PM Open",                       "PM Open",                       200, "PM Open"))
results.append(case("AM Open",                       "AM Open",                       200, "AM Open"))
results.append(case("Previous max",                  "Previous max",                  200, "Previous max"))
results.append(case("Previous min",                  "Previous min",                  200, "Previous min"))
results.append(case("Candle Range %",                "Candle Range %",                200, "Candle Range %"))
results.append(case("Elapsed time from last High",   "Elapsed time from last High",   200, "Elapsed time from last High"))
results.append(case("Yesterday Volume",              "Yesterday Volume",              200, "Yesterday Volume"))
results.append(case("High of last X days",           "High of last X days",           200, "High of last X days"))
results.append(case("Low of last X days",            "Low of last X days",            200, "Low of last X days"))
results.append(case("Donchian",                      "Donchian",                      200, "Donchian"))

print()
print("=== LEGACY ALIASES (should 200, normalized to new) ===")
results.append(case("legacy: Pre-Market High",       "Pre-Market High",               200, "PM High"))
results.append(case("legacy: Pre-Market Low",        "Pre-Market Low",                200, "PM Low"))
results.append(case("legacy: Max of last X days",    "Max of last X days",            200, "High of last X days"))
results.append(case("legacy: Min of last X days",    "Min of last X days",            200, "Low of last X days"))
results.append(case("legacy: Donchian Channels",     "Donchian Channels",             200, "Donchian"))

print()
print("=== INDICATOR-VS-INDICATOR (PM High > RTH Open) ===")
results.append(case("PM High > RTH Open",            "PM High",                       200, "PM High", tgt="RTH Open"))

print()
print("=== REMOVED / INVALID (should 422) ===")
results.append(case("Yesterday Accumulated Volume",  "Yesterday Accumulated Volume",  422))
results.append(case("garbage name",                  "Totally Made Up Indicator",     422))

print()
print(f"=== SUMMARY: {sum(results)}/{len(results)} passed ===")
sys.exit(0 if all(results) else 1)
