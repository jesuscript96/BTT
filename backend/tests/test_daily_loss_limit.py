"""Cortacircuitos de perdida diaria: el dia se corta y deja de operar.

Se prueban las dos capas por separado:

  1. El SIMULADOR obedece el corte (`no_new_risk_after`, `force_close_at`) —
     tanto el motor Python como el JIT, que deben coincidir.
  2. El BUCLE DEL DIA calcula bien el instante T y descarta lo que toca, con
     tickers cuyo orden alfabetico NO coincide con el cronologico, que es
     justo donde una implementacion ingenua se equivoca.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.services.portfolio_sim import simulate as simulate_py
from app.services.sim_dispatch import simulate_jit


def _serie(precios, entradas_en, salidas_en=(), t0_min=0):
    """Arrays de un ticker-dia de un minuto por barra.

    Las salidas hacen falta de verdad: sin ellas la posicion no se cierra hasta
    el fin de dia y una segunda entrada nunca llega a dispararse.
    """
    n = len(precios)
    close = np.asarray(precios, dtype=np.float64)
    entries = np.zeros(n, dtype=bool)
    for i in entradas_en:
        entries[i] = True
    exits = np.zeros(n, dtype=bool)
    for i in salidas_en:
        exits[i] = True
    ts = ((np.arange(n) + t0_min) * 60_000_000_000).astype(np.int64)
    return {
        "close": close,
        "open_": close,
        "high": close * 1.001,
        "low": close * 0.999,
        "entries": entries,
        "exits": exits,
        "timestamps": ts,
    }


def _sim(fn, s, **kw):
    return fn(
        close=s["close"], open_=s["open_"], high=s["high"], low=s["low"],
        entries=s["entries"], exits=s["exits"], direction="longonly",
        init_cash=10_000.0, risk_r=1_000.0, risk_type="FIXED",
        timestamps=s["timestamps"], accumulate=True, max_reentries=-1, **kw
    )


# ── 1. El simulador obedece ──────────────────────────────────────────────

@pytest.mark.parametrize("motor", [simulate_py, simulate_jit])
def test_bloquea_entradas_posteriores_al_corte(motor):
    # Dos entradas: barra 1 y barra 6. El corte se pone en la barra 4.
    # Entra en 1 (ejecuta en 2), sale en 3; vuelve a entrar en 6.
    s = _serie([10, 10, 11, 11, 10, 10, 10, 12, 12, 12], entradas_en=[1, 6], salidas_en=[3])
    sin_corte = _sim(motor, s)
    con_corte = _sim(motor, s, no_new_risk_after=int(s["timestamps"][6]))

    assert len(sin_corte["trades"]) == 2, "el caso base debe dar dos trades"
    assert len(con_corte["trades"]) == 1, "la segunda entrada es posterior a T"
    # La primera operacion queda EXACTAMENTE igual: el corte no reescribe el pasado.
    assert con_corte["trades"][0]["entry_idx"] == sin_corte["trades"][0]["entry_idx"]
    assert con_corte["trades"][0]["pnl"] == sin_corte["trades"][0]["pnl"]


@pytest.mark.parametrize("motor", [simulate_py, simulate_jit])
def test_cierre_forzado_en_el_instante_del_corte(motor):
    s = _serie([10, 10, 11, 12, 13, 14, 15, 16, 17, 18], entradas_en=[1])
    t_corte = int(s["timestamps"][5])
    con_cierre = _sim(motor, s, no_new_risk_after=t_corte, force_close_at=t_corte)

    assert len(con_cierre["trades"]) == 1
    t = con_cierre["trades"][0]
    assert t["exit_idx"] == 5, "debe cerrar en la barra del corte, no al final del dia"
    assert t["exit_reason"] == "Daily Limit"


def test_los_dos_motores_coinciden_con_corte():
    """El corte no puede abrir una grieta entre el motor Python y el JIT."""
    s = _serie([10, 10, 11, 9, 8, 10, 10, 12, 11, 11], entradas_en=[1, 6], salidas_en=[3])
    t = int(s["timestamps"][4])
    a = _sim(simulate_py, s, no_new_risk_after=t, force_close_at=t)
    b = _sim(simulate_jit, s, no_new_risk_after=t, force_close_at=t)
    assert len(a["trades"]) == len(b["trades"])
    for ta, tb in zip(a["trades"], b["trades"]):
        assert ta["entry_idx"] == tb["entry_idx"]
        assert ta["exit_idx"] == tb["exit_idx"]
        assert ta["exit_reason"] == tb["exit_reason"]
        assert ta["pnl"] == pytest.approx(tb["pnl"])


def test_apagado_por_defecto_no_cambia_nada():
    s = _serie([10, 10, 11, 9, 8, 10, 10, 12, 11, 11], entradas_en=[1, 6], salidas_en=[3])
    base = _sim(simulate_py, s)
    con_ceros = _sim(simulate_py, s, no_new_risk_after=0, force_close_at=0)
    assert base["trades"] == con_ceros["trades"]


# ── 2. El bucle del dia calcula bien T ───────────────────────────────────

def _sig(ticker, precios, entradas_en, salidas_en=(), t0_min=0):
    s = _serie(precios, entradas_en, salidas_en, t0_min=t0_min)
    ts = s["timestamps"]
    return {
        "date": "2026-01-05",
        "ticker": ticker,
        "arrays": {
            "close": s["close"], "open": s["open_"], "high": s["high"],
            "low": s["low"], "timestamp": ts.astype("datetime64[ns]"),
        },
        "entries_arr": s["entries"],
        "exits_arr": s["exits"],
        "timestamps_arr": ts,
        "sig_direction": "longonly",
        "sig_accept_reentries": False,
        "sig_max_reentries": -1,
        "sig_sl_stop": None,
        "sig_sl_trail": False,
        "sig_tp_stop": None,
        "sig_tp_time_limit": None,
        "sig_trail_pct": None,
        "sig_partial_tps": [],
        "gap_pct": 0.0,
    }


def _params(limite=None):
    p = {
        "init_cash": 10_000.0, "risk_r": 1_000.0, "risk_type": "FIXED",
        "fixed_ratio_delta": 500.0, "size_by_sl": False,
        "fees": 0.0, "fee_type": "PERCENT", "slippage": 0.0,
        "locates_cost": 0.0, "locate_type": "FLAT",
        "look_ahead_prevention": True, "strategy_def": {},
        "elapsed_limit": -1.0, "elapsed_operator": "GREATER_THAN_OR_EQUAL",
        "daily_loss_limit": limite,
    }
    return p


def test_el_corte_va_por_hora_real_no_por_orden_alfabetico():
    """El ticker que debe caer es el que entra MAS TARDE, no el ultimo del abecedario.

    AAA pierde temprano, ZZZ pierde despues y cruza el limite, y BBB entra
    todavia mas tarde. Por orden alfabetico BBB va ANTES que ZZZ, asi que una
    implementacion que corte siguiendo el bucle dejaria vivo a BBB y mataria a
    ZZZ — justo al reves de lo que pasaria en vivo.
    """
    from app.services.backtest_signals import simulate_and_accumulate

    # 100 acciones por trade (risk_r 1000 / precio 10).
    # AAA cierra en la barra 4 con ~-100; ZZZ cierra en la 6 con ~-100 (el que
    # cruza el limite de 150); BBB entraría en la 8, ya despues del corte.
    aaa = _sig("AAA", [10, 10, 10, 9, 9, 9, 9, 9, 9, 9], entradas_en=[1], salidas_en=[3])
    zzz = _sig("ZZZ", [10, 10, 10, 10, 10, 9, 9, 9, 9, 9], entradas_en=[3], salidas_en=[5])
    bbb = _sig("BBB", [10, 10, 10, 10, 10, 10, 10, 10, 8, 8], entradas_en=[7], salidas_en=[9])
    dia = sorted([aaa, zzz, bbb], key=lambda s: (s["date"], s["ticker"]))
    assert [s["ticker"] for s in dia] == ["AAA", "BBB", "ZZZ"]

    sin_tope = simulate_and_accumulate(dia, _params(None))
    tickers_sin = {t["ticker"] for t in sin_tope[0]}
    assert tickers_sin == {"AAA", "BBB", "ZZZ"}, "el caso base opera los tres"

    # Limite de 150 $: AAA pierde ~100 y ZZZ, al cerrar despues, lo cruza.
    limite = {"enabled": True, "unit": "CASH", "value": 150.0, "on_open_positions": "LET_RUN"}
    trades, _eq, _dr, _loc, log = simulate_and_accumulate(dia, _params(limite))

    tickers = {t["ticker"] for t in trades}
    assert "BBB" not in tickers, "BBB entra despues del corte: no debe operar"
    assert {"AAA", "ZZZ"} <= tickers, "lo anterior al corte se conserva intacto"

    assert len(log) == 1
    assert log[0]["date"] == "2026-01-05"
    assert log[0]["limit_usd"] == 150.0
    assert log[0]["loss_at_cut"] <= -150.0


def test_sin_limite_no_hay_bitacora_ni_cambios():
    from app.services.backtest_signals import simulate_and_accumulate

    aaa = _sig("AAA", [10, 10, 10, 9, 9, 9, 9, 9, 9, 9], entradas_en=[1], salidas_en=[3])
    bbb = _sig("BBB", [10, 10, 10, 10, 10, 10, 10, 10, 8, 8], entradas_en=[7], salidas_en=[9])
    dia = [aaa, bbb]

    apagado = simulate_and_accumulate(dia, _params(None))
    explicito = simulate_and_accumulate(
        dia, _params({"enabled": False, "unit": "CASH", "value": 150.0})
    )
    assert apagado[0] == explicito[0]
    assert apagado[4] == [] and explicito[4] == []


def test_limite_en_porcentaje_del_capital_de_apertura():
    from app.services.backtest_signals import simulate_and_accumulate

    aaa = _sig("AAA", [10, 10, 10, 9, 9, 9, 9, 9, 9, 9], entradas_en=[1], salidas_en=[3])
    bbb = _sig("BBB", [10, 10, 10, 10, 10, 10, 10, 10, 8, 8], entradas_en=[7], salidas_en=[9])
    dia = [aaa, bbb]

    # 1% de 10.000 = 100 $. AAA pierde ~100 y ya cruza.
    limite = {"enabled": True, "unit": "PCT", "value": 1.0, "on_open_positions": "LET_RUN"}
    trades, _eq, _dr, _loc, log = simulate_and_accumulate(dia, _params(limite))
    assert len(log) == 1
    assert log[0]["limit_usd"] == 100.0
    assert "BBB" not in {t["ticker"] for t in trades}
