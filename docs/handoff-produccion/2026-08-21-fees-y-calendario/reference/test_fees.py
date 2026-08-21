"""
Modelo de comisiones por ejecución (fill) — PROXIMOS_ITEMS ITEM 2, spec
corregida 2026-08-21 (notas A/B/C aplicadas).

Semántica bloqueada:
- `fee_type="FLAT"`: `fees` = **$ por acción y lado**. Fee de un fill =
  `fees × size` del fill.
- `fee_type="PERCENT"`: `fees` = **fracción del nocional por lado** (el
  frontend YA divide /100 en `BacktestPanel.tsx:688` → NO dividir aquí).
  Fee de un fill = `precio_neto × size × fees`.
- Por-fill: la ENTRADA de todo el tamaño se cobra en el bloque de cierre
  final (`original_size`); cada parcial paga solo la salida de sus acciones.
- Quirk contractual (nota B): los parciales NO llevan clave `fees` y el
  total reportado los excluye. Se mantiene a propósito.
- El fee NUNCA depende del PnL (bug 2 viejo: `abs(gross_pnl) * fees`).

OHLC sintético determinista: señal en barra 0 → entrada en open_[1] = 100.0
(look_ahead_prevention), salida EOD en close[n-1]. Sizing exacto vía
risk_type=FIXED: size = risk_r / entry.
"""
import numpy as np
import pytest

from app.services.portfolio_sim import simulate as sim_py
from app.services.sim_dispatch import simulate_jit, warmup


@pytest.fixture(scope="module", autouse=True)
def _warm():
    warmup()


def _ohlc(rows):
    """[(open, high, low, close), ...] -> arrays numpy float64."""
    arr = np.asarray(rows, dtype=np.float64)
    n = len(rows)
    entries = np.zeros(n, dtype=bool)
    entries[0] = True
    return {
        "close": arr[:, 3], "open_": arr[:, 0], "high": arr[:, 1], "low": arr[:, 2],
        "entries": entries, "exits": np.zeros(n, dtype=bool),
    }


# Entrada 100.0, size 1000 (risk_r = 1000 × 100), EOD a 102.0.
_ROWS_EXIT_102 = [
    (100.0, 100.1,  99.9, 100.0),  # señal
    (100.0, 100.6,  99.5, 100.5),  # entrada open=100
    (101.0, 102.0, 100.8, 101.8),
    (102.0, 102.5, 101.5, 102.0),  # EOD close=102
]
_BASE_FLAT_1000 = {
    "direction": "longonly",
    "init_cash": 200_000.0,
    "risk_r": 100_000.0,        # size = 100000 / 100 = 1000 acciones
    "risk_type": "FIXED",
    "fee_type": "FLAT",
    "fees": 0.01,               # $ por acción y lado
    "slippage": 0.0,
    "look_ahead_prevention": True,
}


def test_flat_cobra_por_accion_y_lado():
    """1000 acc × $0.01 → $10 entrada + $10 salida = $20 (antes: $0.02 fijos)."""
    res = sim_py(**_ohlc(_ROWS_EXIT_102), **_BASE_FLAT_1000)
    assert len(res["trades"]) == 1
    t = res["trades"][0]
    assert t["exit_reason"] == "EOD"
    assert t["size"] == pytest.approx(1000.0)
    assert t["fees"] == pytest.approx(20.0, abs=1e-9)
    assert t["pnl"] == pytest.approx(1980.0, abs=1e-6)  # (102-100)×1000 − 20


def test_percent_fraccion_de_nocional_sin_dividir_100():
    """0.01% sobre nocional: fees llega como FRACCIÓN (0.0001). $10.000 por
    lado de entrada → $1; salida 102×100=$10.200 → $1.02. Total $2.02."""
    rows = [
        (100.0, 100.1,  99.9, 100.0),
        (100.0, 100.6,  99.5, 100.5),
        (101.0, 102.0, 100.8, 101.8),
        (102.0, 102.5, 101.5, 102.0),
    ]
    cfg = {**_BASE_FLAT_1000, "fee_type": "PERCENT", "fees": 0.0001,
           "risk_r": 10_000.0}  # size = 100
    res = sim_py(**_ohlc(rows), **cfg)
    t = res["trades"][0]
    assert t["size"] == pytest.approx(100.0)
    assert t["fees"] == pytest.approx(2.02, abs=1e-6)
    assert t["pnl"] == pytest.approx(197.98, abs=1e-6)


def test_percent_trade_plano_tambien_paga():
    """El fee no puede depender del PnL (bug 2): salida exactamente a entrada
    → gross 0, fee $2 (2 lados de $10.000 al 0.01%), pnl −$2. Antes: fee 0."""
    rows = [
        (100.0, 100.1,  99.9, 100.0),
        (100.0, 100.4,  99.6, 100.2),
        (100.2, 100.5,  99.8, 100.1),
        (100.0, 100.4,  99.7, 100.0),  # EOD close=100 = entrada
    ]
    cfg = {**_BASE_FLAT_1000, "fee_type": "PERCENT", "fees": 0.0001,
           "risk_r": 10_000.0}  # size = 100, nocional $10.000/lado
    res = sim_py(**_ohlc(rows), **cfg)
    t = res["trades"][0]
    assert t["fees"] == pytest.approx(2.0, abs=1e-6)
    assert t["pnl"] == pytest.approx(-2.0, abs=1e-6)


def test_parcial_paga_su_salida_y_el_final_la_entrada():
    """Parcial 30% (FLAT $0.01, 1000 acc): el parcial paga 300×$0.01 = $3
    (sin clave fees — quirk B); el cierre final paga la entrada COMPLETA +
    su salida: (1000 + 700) × $0.01 = $17."""
    rows = [
        (100.0, 100.1,  99.9, 100.0),
        (100.0, 100.4,  99.6, 100.2),  # entrada; sin TP aún (< 102)
        (101.0, 102.5, 100.9, 102.3),  # high ≥ 102 → parcial al nivel 102
        (102.3, 102.8, 101.8, 102.4),  # EOD close=102.4
    ]
    res = sim_py(
        **_ohlc(rows), **_BASE_FLAT_1000,
        partial_take_profits=[{"distance_pct": 0.02, "capital_pct": 0.3}],
    )
    assert len(res["trades"]) == 2
    parcial, final = res["trades"]
    assert parcial["exit_reason"] == "Partial TP"
    assert parcial["size"] == pytest.approx(300.0)
    assert parcial["pnl"] == pytest.approx(597.0, abs=1e-6)  # 600 − 3
    assert "fees" not in parcial, "quirk contractual B: el parcial no lleva fees"
    assert final["exit_reason"] == "EOD"
    assert final["size"] == pytest.approx(700.0)
    assert final["fees"] == pytest.approx(17.0, abs=1e-9)   # (1000 + 700) × 0.01
    assert final["pnl"] == pytest.approx(1663.0, abs=1e-6)  # 2.4×700 − 17


def test_parcial_percent():
    """Mismo caso con PERCENT 0.01%: parcial 3.06; final 17.168."""
    rows = [
        (100.0, 100.1,  99.9, 100.0),
        (100.0, 100.4,  99.6, 100.2),
        (101.0, 102.5, 100.9, 102.3),
        (102.3, 102.8, 101.8, 102.4),
    ]
    cfg = {**_BASE_FLAT_1000, "fee_type": "PERCENT", "fees": 0.0001,
           "risk_r": 10_000.0}
    res = sim_py(
        **_ohlc(rows), **cfg,
        partial_take_profits=[{"distance_pct": 0.02, "capital_pct": 0.3}],
    )
    parcial, final = res["trades"]
    assert parcial["size"] == pytest.approx(30.0)
    assert parcial["pnl"] == pytest.approx(59.694, abs=1e-6)  # 60 − 0.306
    assert "fees" not in parcial
    assert final["size"] == pytest.approx(70.0)
    assert final["fees"] == pytest.approx(1.7168, abs=1e-6)   # (10.000 + 7.168) × 0.0001
    assert final["pnl"] == pytest.approx(166.2832, abs=1e-4)  # 168 − 1.7168


def test_paridad_jit_python():
    """Mismos casos (parcial FLAT y full PERCENT) por los dos motores:
    trades idénticos (dict equality tras el redondeo contractual)."""
    rows = [
        (100.0, 100.1,  99.9, 100.0),
        (100.0, 100.4,  99.6, 100.2),
        (101.0, 102.5, 100.9, 102.3),
        (102.3, 102.8, 101.8, 102.4),
    ]
    for cfg in (
        {**_BASE_FLAT_1000,
         "partial_take_profits": [{"distance_pct": 0.02, "capital_pct": 0.3}]},
        {**_BASE_FLAT_1000, "fee_type": "PERCENT", "fees": 0.0001, "risk_r": 10_000.0},
    ):
        kwargs = {**_ohlc(rows), **cfg}
        a = sim_py(**kwargs)
        b = simulate_jit(**kwargs)
        assert a["trades"] == b["trades"], f"trades difieren: {cfg['fee_type']}"
        np.testing.assert_array_equal(a["equity"], b["equity"])
