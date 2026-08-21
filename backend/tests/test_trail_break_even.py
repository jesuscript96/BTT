"""
Trailing Break-Even desacoplado (activation_pct) — PROXIMOS_ITEMS ITEM 1.

Semántica bloqueada (portfolio_sim.py bloque trailing, kernel JIT espejo):
- `trail_activation` (fracción, >0) = umbral de activación propio; si es None,
  el umbral es la propia distancia (trail_pct) → trailing clásico de siempre.
- `trail_pct == 0` tras activarse → stop FIJO en el precio de entrada (BE):
  el trade queda "gratis" (salvo gap a través del stop / fees).
- El stop de trailing (incluido BE) solo ejecuta si queda POR ENCIMA del hard
  stop en long (por debajo en short).
- Episilons ±1e-9 idénticos en Python y JIT (la paridad vive en
  test_sim_jit_equivalence.py::test_trail_activation_equivalence).

OHLC sintético determinista: señal en la barra 0 → la entrada llena en
open_[1] = 100.0 (look_ahead_prevention), size = 1.0 (risk_r=100 FIXED,
fees/slippage 0). Los valores esperados se calculan a mano barra a barra.
"""
import numpy as np
import pytest

from app.services.portfolio_sim import simulate


def _ohlc(rows):
    """[(open, high, low, close), ...] -> arrays numpy float64."""
    arr = np.asarray(rows, dtype=np.float64)
    o, h, l, c = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    n = len(rows)
    entries = np.zeros(n, dtype=bool)
    entries[0] = True
    exits = np.zeros(n, dtype=bool)
    return {
        "close": c, "open_": o, "high": h, "low": l,
        "entries": entries, "exits": exits,
    }


BASE = {
    "direction": "longonly",
    "init_cash": 10_000.0,
    "risk_r": 100.0,
    "risk_type": "FIXED",
    "fees": 0.0,
    "slippage": 0.0,
    "sl_stop": 0.05,       # hard SL long = 100 × 0.95 = 95.0
    "sl_trail": True,
    "look_ahead_prevention": True,
}


def test_t1_be_puro_long():
    """T1: +2% activa (umbral 1%), cae a la entrada → Trailing con pnl 0."""
    pair = _ohlc([
        (100.0, 100.1,  99.9, 100.0),  # señal
        (100.0, 100.5,  99.6, 100.2),  # entrada open=100; no activa (<101)
        (101.0, 102.0, 101.0, 101.8),  # high>=101 activa BE; low>100 no dispara
        (101.0, 101.5,  99.5,  99.5),  # low toca 100 → sale en BE exacto
        ( 99.5,  99.8,  99.0,  99.5),
    ])
    res = simulate(**pair, **BASE, trail_pct=0.0, trail_activation=0.01)
    assert len(res["trades"]) == 1
    t = res["trades"][0]
    assert t["entry_price"] == pytest.approx(100.0)
    assert t["exit_reason"] == "Trailing"
    # gap a través del stop: exit = max(stop, low) = max(100, 99.5) = 100
    assert t["exit_price"] == pytest.approx(100.0)
    assert t["pnl"] == pytest.approx(0.0, abs=1e-9)


def test_t2_sin_activacion_cae_al_hard_sl():
    """T2: nunca llega a +1% → el BE no existe → sale por hard SL."""
    pair = _ohlc([
        (100.0, 100.1,  99.9, 100.0),
        (100.0, 100.4,  99.5, 100.2),  # máximo del trade: 100.4 < 101
        (100.2, 100.3,  97.0,  97.5),
        ( 97.5,  99.0,  94.0,  94.5),  # low <= 95 → hard SL
        ( 94.5,  95.0,  94.0,  94.8),
    ])
    res = simulate(**pair, **BASE, trail_pct=0.0, trail_activation=0.01)
    assert len(res["trades"]) == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "SL"
    assert t["exit_price"] == pytest.approx(95.0)


def test_t3_activacion_mas_distancia():
    """T3: activation 1% + buffer 1% → stop = máximo − entry×0.01."""
    pair = _ohlc([
        (100.0, 100.1,  99.9, 100.0),
        (100.0, 100.2,  99.8, 100.1),  # no activa
        (100.5, 102.0, 101.2, 101.9),  # activa; stop = 102 − 1 = 101; low 101.2 no toca
        (101.5, 103.0, 101.5, 102.8),  # extreme 103 → stop 102; low 101.5 dispara
        (102.5, 103.5, 102.0, 103.0),
    ])
    res = simulate(**pair, **BASE, trail_pct=0.01, trail_activation=0.01)
    assert len(res["trades"]) == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "Trailing"
    assert t["exit_price"] == pytest.approx(102.0)  # max(103 − 100×0.01, low)
    assert t["pnl"] == pytest.approx(2.0)           # (102 − 100) × size 1


def test_t4_espejo_short():
    """T4: BE puro short: −2% activa, rebota a la entrada → Trailing pnl 0."""
    pair = _ohlc([
        (100.0, 100.1,  99.9, 100.0),
        (100.0, 100.5,  99.6,  99.9),  # entrada short open=100; no activa (>99)
        ( 99.5,  99.5,  98.0,  98.2),  # low<=99 activa BE; high 99.5 < 100 no dispara
        ( 98.5, 100.5,  98.3, 100.2),  # high toca 100 → sale en BE exacto
        (100.2, 100.6,  99.9, 100.1),
    ])
    res = simulate(**pair, **{**BASE, "direction": "shortonly"},
                   trail_pct=0.0, trail_activation=0.01)
    assert len(res["trades"]) == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "Trailing"
    # short: exit = min(stop, high) = min(100, 100.5) = 100
    assert t["exit_price"] == pytest.approx(100.0)
    assert t["pnl"] == pytest.approx(0.0, abs=1e-9)


def test_t5_regresion_trailing_clasico_bit_identica():
    """T5: sin activation, el trailing clásico es bit-idéntico al comportamiento
    previo al refactor (umbral de activación = la propia distancia).

    Se llama dos veces: (A) trail_activation=None (contrato actual) y
    (B) trail_activation=trail_pct (semántica del parsing viejo simulado).
    trades y equity deben ser EXACTAMENTE iguales (dict equality + array
    equality): cualquier divergencia significa que el desacople cambió el
    orden de operaciones FP del path clásico.
    """
    trailing_exits = 0
    for ci in range(40):
        rng = np.random.default_rng(70_000 + ci)
        n_bars = int(rng.choice([390, 700]))
        close = 20.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n_bars)))
        open_ = close * np.exp(rng.normal(0, 0.003, n_bars))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n_bars)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n_bars)))
        entries = rng.random(n_bars) < 0.03
        exits = rng.random(n_bars) < 0.02
        cfg = {
            "direction": rng.choice(["longonly", "shortonly"]),
            "init_cash": float(rng.choice([10_000.0, 50_000.0])),
            "risk_r": 100.0,
            "risk_type": str(rng.choice(["FIXED", "PERCENT"])),
            "fees": 0.0,
            "slippage": float(rng.choice([0.0, 0.001])),
            "look_ahead_prevention": bool(rng.random() < 0.5),
            "accumulate": bool(rng.random() < 0.5),
            "sl_stop": float(rng.choice([0.03, 0.08])),
            "sl_trail": True,
            "trail_pct": float(rng.choice([0.02, 0.05, 0.10])),
        }
        kwargs = {
            "close": close, "open_": open_, "high": high, "low": low,
            "entries": entries, "exits": exits, **cfg,
        }
        a = simulate(**kwargs, trail_activation=None)
        b = simulate(**kwargs, trail_activation=kwargs["trail_pct"])
        assert a["trades"] == b["trades"], f"trades difieren cfg={ci}"
        np.testing.assert_array_equal(a["equity"], b["equity"])
        trailing_exits += sum(1 for t in a["trades"] if t["exit_reason"] == "Trailing")
    assert trailing_exits > 0, "el grid no ejercitó salidas Trailing"
