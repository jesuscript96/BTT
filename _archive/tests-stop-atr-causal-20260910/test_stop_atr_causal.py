"""Stop por ATR Multiplier SIN look-ahead (regresión del hallazgo 9-sep).

Antes del fix, `sl_stop` era una fracción FIJA derivada de la MEDIA del ATR de
todo el día — barras posteriores a la entrada incluidas. Medido por Sailor
(docs/MEMORIA.md, 2026-09-09): una entrada matinal de un día que explotaba en
la barra 330 recibía un stop 4,6× más ancho del que le correspondía, y dentro
de la explosión 5× más estrecho. Además no era un stop por ATR de verdad: la
misma distancia para una entrada de las 07:00 que para una de las 15:00.

Desde el 2026-09-10 el stop se fija EN la entrada, por la vía del NIVEL (como
HOD/LOD): `entry ∓ multiplicador × ATR(vela de señal)`. Estos tests clavan la
semántica con una serie ATR fabricada a mano, para que el ATR de la vela de
señal y solo él decida la distancia.
"""
import numpy as np

from app.services.portfolio_sim import simulate


def _dia(n=40, precio=100.0):
    close = np.full(n, precio, dtype=np.float64)
    open_ = np.full(n, precio, dtype=np.float64)
    high = np.full(n, precio, dtype=np.float64)
    low = np.full(n, precio, dtype=np.float64)
    entries = np.zeros(n, dtype=bool)
    entries[20] = True          # señal en la barra 20 → fill en open[21]
    exits = np.zeros(n, dtype=bool)
    return close, open_, high, low, entries, exits


def _atr_con_pico(n=40, base=0.10, pico_idx=20, pico=0.50):
    atr = np.full(n, base, dtype=np.float64)
    atr[pico_idx] = pico
    return atr


def test_long_stop_con_atr_de_la_vela_de_senal():
    close, open_, high, low, entries, exits = _dia()
    atr = _atr_con_pico()
    low[25] = 98.5              # atraviesa el stop, no antes
    res = simulate(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction="longonly",
        hs_type="ATR Multiplier", hs_value=2.0,
        atr_arr=atr, look_ahead_prevention=True,
    )
    (t,) = res["trades"]
    entry = 100.0               # open[21], sin slippage
    # El ATR de la vela de SEÑAL (0,50 en la barra 20) y SOLO él:
    # stop = 100 - 2 x 0,50 = 99,00. La media del día (~0,115) daría ~99,77 —
    # ese es exactamente el look-ahead que este test viene a enterrar.
    assert t["stop_loss"] == round(entry - 2.0 * atr[20], 6)
    assert t["stop_loss"] == 99.0
    assert t["exit_reason"] == "SL"
    assert t["exit_price"] == 99.0        # max(stop, low de la vela)


def test_short_stop_con_atr_de_la_vela_de_senal():
    close, open_, high, low, entries, exits = _dia()
    atr = _atr_con_pico()
    high[25] = 101.5
    res = simulate(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction="shortonly",
        hs_type="ATR Multiplier", hs_value=2.0,
        atr_arr=atr, look_ahead_prevention=True,
    )
    (t,) = res["trades"]
    # Corto: el stop queda POR ENCIMA. stop = 100 + 2 x 0,50 = 101,00.
    assert t["stop_loss"] == round(100.0 + 2.0 * atr[20], 6)
    assert t["stop_loss"] == 101.0
    assert t["exit_reason"] == "SL"
    assert t["exit_price"] == 101.0       # min(stop, high de la vela)


def test_dos_entradas_con_atr_distinto_no_comparten_stop():
    """La queja de fondo del hallazgo: era una CONSTANTE diaria. Ahora la
    distancia la dicta el ATR vivo de cada vela de señal."""
    n = 60
    close, open_, high, low, entries, exits = _dia(n=n)
    entries[20] = True
    entries[40] = True
    atr = np.full(n, 0.10, dtype=np.float64)
    atr[20] = 0.50               # señal de la mañana: volatilidad alta
    atr[40] = 0.02               # señal de la tarde: calma
    low[25] = 97.0               # tumba la primera (stop 99,00)
    low[45] = 99.5               # tumba la segunda (stop 99,96)
    res = simulate(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction="longonly",
        hs_type="ATR Multiplier", hs_value=2.0,
        atr_arr=atr, look_ahead_prevention=True,
        accumulate=True,
    )
    assert len(res["trades"]) == 2
    t1, t2 = res["trades"]
    assert t1["stop_loss"] == 99.0            # 100 - 2 x 0,50
    assert t2["stop_loss"] == round(100.0 - 2.0 * 0.02, 6)   # 99,96


def test_atr_sin_dato_en_la_senal_cae_al_5_pct():
    """Primeras velas del día (ATR todavía NaN): misma convención que el nivel
    estructural ausente — 5 % alrededor de la entrada."""
    close, open_, high, low, entries, exits = _dia()
    atr = _atr_con_pico()
    atr[20] = np.nan
    low[25] = 94.0
    res = simulate(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction="longonly",
        hs_type="ATR Multiplier", hs_value=2.0,
        atr_arr=atr, look_ahead_prevention=True,
    )
    (t,) = res["trades"]
    assert t["stop_loss"] == 95.0             # 100 x 0,95
    assert t["exit_reason"] == "SL"


def test_multiplicador_invalido_no_inventa_stop():
    """value=0 era "sin stop" en la fórmula antigua (sl_stop=0) y sigue
    siéndolo: la posición aguanta hasta EOD aunque el precio se hunda."""
    close, open_, high, low, entries, exits = _dia()
    atr = _atr_con_pico()
    low[30] = 50.0               # desplome del 50 %
    res = simulate(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction="longonly",
        hs_type="ATR Multiplier", hs_value=0,
        atr_arr=atr, look_ahead_prevention=True,
    )
    (t,) = res["trades"]
    assert t["stop_loss"] == 0.0
    assert t["exit_reason"] == "EOD"


def test_stop_en_lado_ganador_invalida_la_entrada():
    """ATR gigante → stop negativo (largo). Un stop que no está en el lado
    perdedor no es un stop: no se entra, igual que el estructural invalidado."""
    close, open_, high, low, entries, exits = _dia()
    atr = _atr_con_pico(pico=1000.0)
    res = simulate(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction="longonly",
        hs_type="ATR Multiplier", hs_value=2.0,
        atr_arr=atr, look_ahead_prevention=True,
    )
    assert res["trades"] == []


def test_sin_serie_cae_a_la_fraccion_compatible():
    """Callers que no emiten `atr_arr` (p. ej. el bot en staging): el ATR
    Multiplier se comporta como la fracción `sl_stop` de siempre."""
    close, open_, high, low, entries, exits = _dia()
    low[25] = 94.0
    res = simulate(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction="longonly",
        sl_stop=0.05,
        hs_type="ATR Multiplier", hs_value=2.0,
        atr_arr=None, look_ahead_prevention=True,
    )
    (t,) = res["trades"]
    assert t["stop_loss"] == 95.0             # 100 x (1 - 0,05)
    assert t["exit_reason"] == "SL"
