"""Tests de la calculadora de locates de Edgie (paquetes de 100, ceil)."""

from app.services.locates import calc_locates


def test_paquetes_ceil_100():
    # 350 shares -> 4 paquetes (nunca 3).
    r = calc_locates(precio_entrada=2.0, precio_stop=2.2, coste_paquete=1.0, shares=350)
    assert r["paquetes_locates"] == 4
    assert r["coste_total_locates"] == 4.0  # 4 paquetes * $1


def test_opcion_riesgo_calcula_shares():
    # riesgo $100, riesgo/share = 0.20 -> 500 shares -> 5 paquetes.
    r = calc_locates(precio_entrada=2.0, precio_stop=2.2, coste_paquete=2.0, riesgo_dolares=100)
    assert r["shares"] == 500
    assert r["paquetes_locates"] == 5


def test_fade_break_even_total():
    r = calc_locates(precio_entrada=10.0, precio_stop=10.5, coste_paquete=5.0, shares=100)
    # riesgo/share=0.5; coste_total=5 (1 paquete); coste/share=0.05
    # fade_total = (0.5+0.05)/10*100 = 5.5%
    assert r["fade_break_even_total_pct"] == 5.5


def test_stop_debe_estar_encima():
    r = calc_locates(precio_entrada=3.0, precio_stop=2.5, coste_paquete=1.0, shares=100)
    assert "error" in r


def test_faltan_datos():
    assert "error" in calc_locates(precio_entrada=2.0, precio_stop=2.2, coste_paquete=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Simulador: atribución del locate diario (PRD fix-locates-attribution).
#
# El locate es UNA compra por ticker-día dimensionada al tamaño máximo en
# corto (max_short_size_today): el TOTAL ya es correcto. Estos tests fijan el
# REPARTO — proporcional al size de cada short (§4.2) — y que la curva de
# equity solo baja desde la barra de la primera entrada corta (§4.3).
# ─────────────────────────────────────────────────────────────────────────────
import numpy as np


def _short_reentry_day(p1=2.0, p2=6.0, risk_r=6000.0, max_reentries=-1):
    """Día sintético shortonly con 2 entradas (reentrada) sin solape.

    Entrada A en open[6] (señal en barra 5) a precio p1; salida por señal en
    barra 30 → fill open[31] = p1 (pnl bruto 0). Entrada B en open[46] a p2
    (señal en 45); salida EOD en close[59] = p2 (pnl bruto 0). Con
    risk_type=FIXED y size_by_sl=False: size = risk_r / precio, así que los
    tamaños se controlan con los precios.
    """
    n = 60
    close = np.full(n, p1)
    open_ = np.full(n, p1)
    high = close * 1.001
    low = close * 0.999
    close[32:] = p2
    open_[32:] = p2
    high[32:] = p2 * 1.001
    low[32:] = p2 * 0.999
    entries = np.zeros(n, dtype=bool)
    entries[5] = True
    entries[45] = True
    exits = np.zeros(n, dtype=bool)
    exits[30] = True
    return dict(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits,
        direction="shortonly", init_cash=10000.0,
        risk_r=risk_r, risk_type="FIXED", size_by_sl=False,
        fees=0.0, slippage=0.0,
        accumulate=True, max_reentries=max_reentries,
    )


def test_locates_reparto_proporcional_y_curva():
    """Caso §5 del PRD: sizes 3000/1000 → fee $90 repartido 67.50/22.50."""
    from app.services.portfolio_sim import simulate

    res = simulate(**_short_reentry_day(p1=2.0, p2=6.0, risk_r=6000.0),
                   locates_cost=3.0, locate_type="FLAT")
    trades = res["trades"]

    assert len(trades) == 2
    assert [t["entry_idx"] for t in trades] == [6, 46]
    assert [round(t["size"], 4) for t in trades] == [3000.0, 1000.0]

    # (i) invariante contable: Σ imputado == daily_locates_fee
    #     (ceil(max_short_size_today=3000 / 100) * $3 = $90)
    assert round(sum(t["fees"] for t in trades), 6) == 90.0

    # (ii) reparto proporcional al size: con ≥2 shorts, NADIE carga el 100%
    assert round(trades[0]["fees"], 4) == 67.5   # 90 * 3000/4000
    assert round(trades[1]["fees"], 4) == 22.5   # 90 * 1000/4000
    assert max(t["fees"] for t in trades) < 90.0
    # pnl bruto 0 en ambos → neto = −share
    assert round(trades[0]["pnl"], 4) == -67.5
    assert round(trades[1]["pnl"], 4) == -22.5

    # (iii) la curva no baja antes de la primera entrada corta (barra 6)
    eq = res["equity"]
    assert eq[0] == 10000.0
    assert eq[5] == 10000.0
    assert round(eq[6], 6) == 10000.0 - 90.0
    assert round(eq[-1], 6) == 10000.0 - 90.0


def test_locates_una_sola_compra_reentrada():
    """§4.4 (defecto 3, NO es bug): el locate se cobra UNA vez por día sobre
    max_short_size_today — no se multiplica por reentradas ni suma tamaños."""
    from app.services.portfolio_sim import simulate

    # Segunda entrada MÁS grande (1000 → 3000): fee sobre el MÁXIMO (3000)
    # = $90, no sobre la suma de tamaños (4000 → $120).
    res = simulate(**_short_reentry_day(p1=6.0, p2=2.0, risk_r=6000.0, max_reentries=2),
                   locates_cost=3.0, locate_type="FLAT")
    trades = res["trades"]
    assert [round(t["size"], 4) for t in trades] == [1000.0, 3000.0]
    assert round(sum(t["fees"] for t in trades), 6) == 90.0

    # Tamaños iguales (1000/1000): fee sobre 1000 = $30, no ×2 = $60.
    res2 = simulate(**_short_reentry_day(p1=2.0, p2=2.0, risk_r=2000.0, max_reentries=2),
                    locates_cost=3.0, locate_type="FLAT")
    trades2 = res2["trades"]
    assert [round(t["size"], 4) for t in trades2] == [1000.0, 1000.0]
    assert round(sum(t["fees"] for t in trades2), 6) == 30.0
