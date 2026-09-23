"""Señal por NIVEL y Previous Max con la vela de la señal (2026-09-20).

Regresión de un caso real (AEMD, 17-sep-2026). Dos reglas del motor que por
separado eran razonables y juntas dejaban tickers sin operar en todo el día:

  1. Se entraba solo en el FLANCO de la señal (apagada → encendida), y el
     flanco se consumía aunque el intento se descartara o la posición
     saliera por stop. Con condiciones que no se apagan (gap > X, precio > X)
     eso era UN intento por ticker-día y cero reentradas.
  2. «Previous Max» del stop era el máximo hasta la vela ANTERIOR. En un gap
     que rompe de golpe, el nivel era el precio de antes de la rotura: el
     stop del corto caía bajo la entrada y `_sl_side_valid` descartaba el
     intento. Sumado a (1): fuera todo el día.

Ahora: fuera de posición y con la señal encendida se intenta entrar
(`max_reentries` cuenta igual que antes: solo las entradas reales), y el stop
«Previous Max/Min (vela de la señal)» (opt-in) mira el máximo/mínimo del día
DESDE la vela de la señal hacia atrás (la vela incluida; la orden sigue en
`i+1`). «Previous Max» a secas sigue siendo el de siempre, hasta la vela
anterior, y es el por defecto. Paridad Python ↔ JIT.
"""
import numpy as np
import pytest

from app.services.portfolio_sim import simulate as sim_py
from app.services.sim_dispatch import simulate_jit, warmup

HS = "Market Structure (HOD/LOD)"
BASE_TS = np.datetime64("2026-09-17T04:00:00").astype("datetime64[ns]").astype(np.int64)


@pytest.fixture(scope="module", autouse=True)
def _warm():
    warmup()


def _ts(n):
    return (BASE_TS + np.arange(n) * 60_000_000_000).astype(np.int64)


def _ambos(**kw):
    a = sim_py(**kw)
    b = simulate_jit(**kw)
    assert len(a["trades"]) == len(b["trades"]), (len(a["trades"]), len(b["trades"]))
    for ta, tb in zip(a["trades"], b["trades"]):
        assert ta["entry_idx"] == tb["entry_idx"]
        assert ta["exit_reason"] == tb["exit_reason"]
    return a


def test_reentra_tras_stop_si_la_senal_sigue_encendida():
    """Corto con stop en %, señal encendida TODO el día, 2 reentradas.

    Antes: 1 trade (el flanco de la barra 1 se consumía y no había otro).
    Ahora: el stop salta, la señal sigue viva y se reentra hasta agotar
    `max_reentries` -> 3 trades.
    """
    n = 30
    close = np.full(n, 10.0); open_ = np.full(n, 10.0)
    high = np.full(n, 10.05); low = np.full(n, 9.95)
    # Cada 5 velas una mecha que salta el stop del 3 %.
    for k in (3, 8, 13, 18, 23):
        high[k] = 10.5
    entries = np.ones(n, dtype=bool); entries[0] = False
    res = _ambos(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=np.zeros(n, dtype=bool), timestamps=_ts(n),
        direction="shortonly", init_cash=10_000.0, risk_r=100.0, risk_type="FIXED",
        sl_stop=0.03, accumulate=True, max_reentries=2,
    )
    tr = res["trades"]
    assert len(tr) == 3, [(t["entry_idx"], t["exit_reason"]) for t in tr]
    assert [t["exit_reason"] for t in tr] == ["SL", "SL", "SL"]
    # La reentrada es INMEDIATA: sale en la vela k y vuelve a entrar en k+1.
    assert tr[1]["entry_idx"] == tr[0]["exit_idx"] + 1


def test_sin_reentradas_sigue_siendo_un_trade():
    """`max_reentries=0` acota igual que antes: la señal viva no lo salta."""
    n = 30
    close = np.full(n, 10.0); open_ = np.full(n, 10.0)
    high = np.full(n, 10.05); low = np.full(n, 9.95)
    high[3] = 10.5
    entries = np.ones(n, dtype=bool); entries[0] = False
    res = _ambos(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=np.zeros(n, dtype=bool), timestamps=_ts(n),
        direction="shortonly", init_cash=10_000.0, risk_r=100.0, risk_type="FIXED",
        sl_stop=0.03, accumulate=True, max_reentries=0,
    )
    assert len(res["trades"]) == 1


def test_intento_descartado_no_consume_la_senal():
    """Previous Max +10 % en corto. El nivel queda del lado ganador las 6
    primeras velas de señal (no se entra) y se resuelve en la séptima: antes
    el ticker quedaba fuera todo el día; ahora entra en cuanto el stop vale.
    """
    n = 30
    close = np.full(n, 10.0); open_ = np.full(n, 10.0)
    high = np.full(n, 10.05); low = np.full(n, 9.95)
    entries = np.ones(n, dtype=bool); entries[0] = False
    # Máximo corrido "viejo" (8.0 -> stop 8.8 < 10, inválido) hasta la vela 6,
    # y a partir de ahí 10.05 (stop 11.05, válido).
    hods = np.where(np.arange(n) < 6, 8.0, 10.05)
    res = _ambos(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=np.zeros(n, dtype=bool), timestamps=_ts(n),
        direction="shortonly", init_cash=10_000.0, risk_r=100.0, risk_type="FIXED",
        hs_type=HS, hs_value="Previous Max (vela de la señal)", hs_operator=">=", hs_offset_pct=10.0,
        hods=hods, accumulate=True, max_reentries=0,
    )
    tr = res["trades"]
    assert len(tr) == 1
    assert tr[0]["entry_idx"] == 7            # señal válida en 6, fill en 7
    assert abs(tr[0]["stop_loss"] - 10.05 * 1.10) < 1e-6


def _aemd():
    """Las tres primeras velas reales de AEMD el 17-sep-2026 (cierre previo
    1,41) más una de relleno para el fill en i+1."""
    n = 4
    open_ = np.array([1.42, 1.40, 1.40, 2.975])
    high = np.array([1.42, 1.40, 3.15, 3.25])
    low = np.array([1.42, 1.40, 1.40, 2.41])
    close = np.array([1.42, 1.40, 2.96, 3.15])
    hods = np.maximum.accumulate(high)
    lods = np.minimum.accumulate(low)
    prev_h = np.empty_like(hods); prev_h[0] = high[0]; prev_h[1:] = hods[:-1]
    prev_l = np.empty_like(lods); prev_l[0] = low[0]; prev_l[1:] = lods[:-1]
    entries = np.array([False, False, True, True])   # gap > 50 % desde la vela 2
    return dict(
        close=close, open_=open_, high=high, low=low, entries=entries,
        exits=np.zeros(n, dtype=bool), timestamps=_ts(n),
        direction="shortonly", init_cash=10_000.0, risk_r=100.0, risk_type="FIXED",
        hs_type=HS, hs_operator=">=", hs_offset_pct=10.0,
        hods=hods, lods=lods, prev_highs=prev_h, prev_lows=prev_l,
        accumulate=True, max_reentries=0,
    )


def test_previous_max_vela_de_la_senal_mira_desde_la_vela_de_la_senal():
    """Señal en la vela de la rotura (i=2, high 3,15). El nivel es 3,15 x 1,10
    = 3,465 > entrada 2,975 (open de i+1): stop válido, entra. Y NO entra en
    la vela de la señal: el fill sigue siendo en i+1."""
    res = _ambos(**_aemd(), hs_value="Previous Max (vela de la señal)")
    tr = res["trades"]
    assert len(tr) == 1
    assert tr[0]["entry_idx"] == 3
    assert tr[0]["entry_price"] == pytest.approx(2.975)
    assert tr[0]["stop_loss"] == pytest.approx(3.15 * 1.10)


def test_previous_max_de_siempre_hasta_la_vela_anterior():
    """Mismo día con «Previous Max» a secas (el por defecto): el nivel en i=2 es el máximo hasta i=1
    (1,42) -> stop 1,56 bajo la entrada del corto -> se descarta. En i=3 el
    máximo hasta i=2 ya es 3,15, pero i=3 es la última vela y no hay i+1 donde
    ejecutar: sin trade. Es el comportamiento de siempre, que sigue siendo el
    por defecto (Jaume, 20-sep)."""
    res = _ambos(**_aemd(), hs_value="Previous Max")
    assert res["trades"] == []


def test_hod_sigue_aceptado_como_alias_de_vela_de_la_senal():
    a = _ambos(**_aemd(), hs_value="HOD")
    b = _ambos(**_aemd(), hs_value="Previous Max (vela de la señal)")
    assert a["trades"][0]["stop_loss"] == pytest.approx(b["trades"][0]["stop_loss"])
