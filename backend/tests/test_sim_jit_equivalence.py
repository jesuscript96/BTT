"""
EPIC D · T-D4 (GATE) — Equivalencia masiva simulate() Python vs kernel Numba.

Property-test determinista (seed fija): ≥200 configuraciones muestreadas del espacio
completo de parámetros × pares sintéticos variados. Exigencia: `trades` IDÉNTICOS
(igualdad de dicts tras el redondeo contractual), `equity` exacta bit a bit y
`last_risk_amount` igual. Si esto falla, se arregla el kernel/adapter — NUNCA se
relaja el test (PRD §6.1).
"""
import numpy as np
import pytest

from app.services.portfolio_sim import simulate as sim_py
from app.services.sim_dispatch import simulate_jit, warmup

RNG = np.random.default_rng(20260702)


@pytest.fixture(scope="module", autouse=True)
def _warm():
    warmup()


def _mk_pair(rng, n_bars):
    close = 8.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n_bars)))
    open_ = close * np.exp(rng.normal(0, 0.003, n_bars))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n_bars)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n_bars)))
    # timestamps: minuto a minuto desde las 07:00 (cruza 08:00-08:45 → patch, y RTH)
    base = 1_756_800_000 * 1_000_000_000 + 7 * 3600 * 1_000_000_000
    ts = (base + np.arange(n_bars) * 60_000_000_000).astype(np.int64)
    entries = rng.random(n_bars) < rng.choice([0.0, 0.01, 0.05])
    exits = rng.random(n_bars) < rng.choice([0.0, 0.01, 0.03])
    hod = np.maximum.accumulate(high)
    lod = np.minimum.accumulate(low)
    prev_h = np.empty_like(hod); prev_h[0] = high[0]; prev_h[1:] = hod[:-1]
    prev_l = np.empty_like(lod); prev_l[0] = low[0]; prev_l[1:] = lod[:-1]
    pm_mask = np.zeros(n_bars, dtype=bool)
    pm_mask[: min(90, n_bars)] = True
    patch = rng.random() < 0.5
    minutes = (ts // 60_000_000_000) % 1440
    patch_mask = ((minutes >= 480) & (minutes < 525)) if patch else None
    return {
        "close": close, "open_": open_, "high": high, "low": low,
        "entries": entries, "exits": exits, "timestamps": ts,
        "hods": hod, "lods": lod,
        "pm_highs": np.full(n_bars, float(high[pm_mask].max()) if pm_mask.any() else 0.0),
        "pm_lows": np.full(n_bars, float(low[pm_mask].min()) if pm_mask.any() else 0.0),
        "prev_highs": prev_h, "prev_lows": prev_l,
        "patch_mask": patch_mask,
    }


def _sample_config(rng):
    """Una configuración aleatoria del espacio completo del contrato (PRD §03.4)."""
    cfg = {
        "direction": rng.choice(["longonly", "shortonly"]),
        "init_cash": float(rng.choice([2000.0, 10000.0, 50000.0])),
        "risk_r": float(rng.choice([50.0, 100.0, 5.0])),
        "risk_type": rng.choice(["FIXED", "PERCENT", "FIXED_RATIO"]),
        "fixed_ratio_delta": float(rng.choice([250.0, 500.0])),
        "size_by_sl": bool(rng.random() < 0.4),
        "fees": float(rng.choice([0.0, 0.01, 2.5])),
        "fee_type": rng.choice(["PERCENT", "FLAT"]),
        "slippage": float(rng.choice([0.0, 0.001])),
        "look_ahead_prevention": bool(rng.random() < 0.5),
        "accumulate": bool(rng.random() < 0.5),
        "max_reentries": int(rng.choice([-1, 0, 2])),
        "locates_cost": float(rng.choice([0.0, 0.0, 1.5])),
        "locate_type": rng.choice(["FLAT", "PERCENT"]),
        "elapsed_limit": float(rng.choice([-1.0, -1.0, 45.0])),
        "elapsed_operator": rng.choice(
            ["GREATER_THAN_OR_EQUAL", "GT", "LESS_THAN", "LTE", "EQUAL"]),
    }
    # stops / TPs
    if rng.random() < 0.6:
        cfg["sl_stop"] = float(rng.choice([0.03, 0.08, 0.15]))
    if rng.random() < 0.4:
        cfg["sl_trail"] = True
        cfg["trail_pct"] = float(rng.choice([0.02, 0.05]))
    if rng.random() < 0.4:
        cfg["tp_stop"] = float(rng.choice([0.02, 0.06]))
    r = rng.random()
    if r < 0.15:
        cfg["tp_time_limit"] = float(rng.choice([15.0, 60.0]))
    elif r < 0.30:
        cfg["tp_time_limit"] = "HOUR:10:30"
    # hard stop Market Structure (todas las variantes de hs_value y alias)
    if rng.random() < 0.45:
        cfg["hs_type"] = "Market Structure (HOD/LOD)"
        cfg["hs_value"] = rng.choice(
            ["HOD", "LOD", "PMH", "PML", "Previous Max", "PrevMax",
             "Previous Min", "PrevMin", "Previous Low", "PrevLow", "otro"])
        cfg["hs_operator"] = rng.choice([">=", "<=", ">", "<"])
        cfg["hs_offset_pct"] = float(rng.choice([0.0, 1.0, 2.5]))
    # partial TPs: 0-3 niveles de los 4 tipos
    if rng.random() < 0.4:
        n_pt = int(rng.integers(1, 4))
        kinds = rng.choice(["pct", "EOD", "TIME", "HOUR"], size=n_pt, replace=True)
        ptps = []
        for k in kinds:
            if k == "pct":
                ptps.append({"distance_pct": float(rng.choice([0.01, 0.03])),
                             "capital_pct": float(rng.choice([0.25, 0.5]))})
            elif k == "EOD":
                ptps.append({"distance_pct": "EOD", "capital_pct": 0.5})
            elif k == "TIME":
                ptps.append({"distance_pct": f"TIME:{int(rng.choice([10, 45]))}",
                             "capital_pct": 0.34})
            else:
                ptps.append({"distance_pct": "HOUR:9:45", "capital_pct": 0.25})
        cfg["partial_take_profits"] = ptps
    return cfg


def _assert_equal(res_py, res_jit, ctx):
    assert res_py["trades"] == res_jit["trades"], (
        f"trades difieren [{ctx}]:\npy : {res_py['trades'][:3]}\njit: {res_jit['trades'][:3]}")
    np.testing.assert_array_equal(res_py["equity"], res_jit["equity"],
                                  err_msg=f"equity difiere [{ctx}]")
    assert res_py["last_risk_amount"] == res_jit["last_risk_amount"], f"last_risk [{ctx}]"


N_CONFIGS = 220
PAIRS_PER_CONFIG = 3


def test_massive_equivalence_grid():
    """220 configs × 3 pares (390/700/960 barras) = 660 simulaciones idénticas."""
    total_trades = 0
    exit_reasons = set()
    for ci in range(N_CONFIGS):
        rng = np.random.default_rng(1000 + ci)
        cfg = _sample_config(rng)
        for n_bars in (390, 700, 960):
            pair = _mk_pair(rng, n_bars)
            kwargs = {**pair, **cfg}
            res_py = sim_py(**kwargs)
            res_jit = simulate_jit(**kwargs)
            _assert_equal(res_py, res_jit, f"cfg={ci} bars={n_bars}")
            total_trades += len(res_py["trades"])
            exit_reasons.update(t["exit_reason"] for t in res_py["trades"])
    # el grid debe haber ejercitado señales de verdad y variedad de salidas
    assert total_trades > 500, f"grid poco representativo: {total_trades} trades"
    assert {"EOD", "Signal", "SL"} <= exit_reasons, f"poca variedad: {exit_reasons}"


def test_exit_reason_coverage():
    """Casos dirigidos: cada exit_reason del contrato aparece y es idéntico."""
    seen = set()
    for ci in range(400):
        rng = np.random.default_rng(50_000 + ci)
        cfg = _sample_config(rng)
        pair = _mk_pair(rng, 700)
        kwargs = {**pair, **cfg}
        res_py = sim_py(**kwargs)
        res_jit = simulate_jit(**kwargs)
        _assert_equal(res_py, res_jit, f"cov={ci}")
        seen.update(t["exit_reason"] for t in res_py["trades"])
        if {"SL", "TP", "Trailing", "Time Limit", "Signal", "EOD",
            "Partial TP", "Partial TP (EOD)", "Partial TP (Time)",
            "Partial TP (Hour)"} <= seen:
            break
    # exigidas siempre; las de reloj dependen del muestreo pero deben salir varias
    assert {"SL", "Signal", "EOD"} <= seen
    assert len(seen) >= 6, f"cobertura de exit_reasons insuficiente: {seen}"


def test_edge_cases_exact():
    """Degenerados: sin señales, todo señales, 5 barras, precios ~0, sin timestamps."""
    rng = np.random.default_rng(7)
    for n_bars, ent_p, price_scale, with_ts in [
        (5, 0.0, 1.0, True), (5, 1.0, 1.0, True), (390, 1.0, 1.0, True),
        (60, 0.05, 0.001, True), (60, 0.05, 1.0, False),
    ]:
        pair = _mk_pair(rng, n_bars)
        pair["close"] = pair["close"] * price_scale
        pair["open_"] = pair["open_"] * price_scale
        pair["high"] = pair["high"] * price_scale
        pair["low"] = pair["low"] * price_scale
        pair["entries"] = rng.random(n_bars) < ent_p
        if not with_ts:
            pair["timestamps"] = None
        for direction in ("longonly", "shortonly"):
            kwargs = {**pair, "direction": direction, "sl_stop": 0.05,
                      "accumulate": True, "locates_cost": 1.0, "locate_type": "FLAT"}
            _assert_equal(sim_py(**kwargs), simulate_jit(**kwargs),
                          f"edge n={n_bars} p={ent_p} dir={direction}")


def test_dispatcher_selects_engine(monkeypatch):
    from app.services import sim_dispatch
    rng = np.random.default_rng(3)
    pair = _mk_pair(rng, 60)
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "0")
    a = sim_dispatch.simulate(**pair)
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    b = sim_dispatch.simulate(**pair)
    assert a["trades"] == b["trades"]
    np.testing.assert_array_equal(a["equity"], b["equity"])
