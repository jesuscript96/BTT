"""
Parciales con disparador dual 1A/1B + métricas MAE/MFE desde máximo previo
(feature Álvaro, 2026-08-19 — diseño validado con el ejemplo "10$ → 20$").

Contrato:
- 1A "fade desde el máximo": nivel = prev_highs[entry] × (1 − G). Dispara cuando
  el precio CAE al nivel (long y short). Skip si el nivel ya está cruzado al
  entrar o si la ganancia desde entrada sería < min_gain (marcado en el trade).
- 1B "% desde entrada": comportamiento histórico intacto.
- OCO por slot: el que "manda" (priority) se evalúa primero si ambos tocan en
  la misma vela; en velas distintas gana el primero en el tiempo. Una sola
  ejecución con SU capital_pct — nunca se suman.
- Campos por trade: prev_max_ref, fade_at_entry_pct, mae_prev_max, mfe_prev_max,
  partials_skipped.
- Paridad legacy (portfolio_sim) ↔ JIT (portfolio_sim_jit) en ambos modos.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import numpy as np
import pytest


def _day(closes, signal_bar=4, lows=None):
    """Frame 1m sintético: entry en signal_bar (lookahead off → fill al close).
    Opens continuos (open[i] = close[i−1]) para que los cruces de nivel se
    llenen AL NIVEL y no al open por gap."""
    close = np.asarray(closes, dtype=np.float64)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(close, open_) + 0.2
    low = (np.asarray(lows, dtype=np.float64) if lows is not None
           else np.minimum(close, open_) - 0.2)
    entries = np.zeros(len(close), dtype=bool)
    entries[signal_bar] = True
    exits = np.zeros(len(close), dtype=bool)
    return close, open_, high, low, entries, exits


def _prev_highs_from(highs):
    """Running max shifted 1 barra (causal), como backtest_service."""
    run = np.maximum.accumulate(np.asarray(highs, dtype=np.float64))
    return np.concatenate([[np.nan], run[:-1]])


def _simulate(use_jit, **kw):
    os.environ["BACKTEST_NUMBA_SIM"] = "1" if use_jit else "0"
    from app.services.sim_dispatch import simulate
    return simulate(**kw)


BASE = dict(direction="shortonly", init_cash=10_000.0, risk_r=100.0,
            look_ahead_prevention=False)


def test_ejemplo_nino_fade_50_desde_max_20():
    """Sube a 20 (high del bar 3), entra short a 16: 1A al 50% del recorrido → vende al tocar 10."""
    closes = [10, 12, 14, 19.8, 16, 15.5, 14, 12, 10.5, 9.9, 9.9]
    close, open_, high, low, entries, exits = _day(closes)
    prev_highs = _prev_highs_from(high)
    assert prev_highs[4] == pytest.approx(20.0), "máximo previo a la entrada = 20"
    pts = [{"distance_pct": 0.45, "capital_pct": 0.5,
            "fade_from_high_pct": 0.50, "min_gain_pct": None, "priority": 0}]
    res = _simulate(False, close=close, open_=open_, high=high, low=low,
                    entries=entries, exits=exits, partial_take_profits=pts,
                    prev_highs=prev_highs, **BASE)
    partials = [t for t in res["trades"] if t["exit_reason"] == "Partial TP (Fade)"]
    assert len(partials) == 1, "el fade debe ejecutar el parcial una sola vez"
    p = partials[0]
    assert p["entry_price"] == pytest.approx(16.0), "entry al close de la vela señal"
    assert p["exit_price"] == pytest.approx(10.0), "nivel = máx 20 × (1 − 50%) = 10"
    t = res["trades"][-1]
    assert t["prev_max_ref"] == pytest.approx(20.0)
    assert t["fade_at_entry_pct"] == pytest.approx(20.0)  # (20−16)/20
    assert t["partials_skipped"] == []


def test_ganancia_minima_salta_el_fade():
    """Entra tarde (10.8): el nivel 10 dejaría 7.4% < 10% → 1A saltado, manda 1B lejano."""
    closes = [10, 12, 14, 19.8, 10.8, 10.6, 10.4, 10.2, 10.1, 10.0, 10.0]
    close, open_, high, low, entries, exits = _day(closes)
    prev_highs = _prev_highs_from(high)
    pts = [{"distance_pct": 0.30, "capital_pct": 0.5,
            "fade_from_high_pct": 0.50, "min_gain_pct": 0.10, "priority": 0}]
    res = _simulate(False, close=close, open_=open_, high=high, low=low,
                    entries=entries, exits=exits, partial_take_profits=pts,
                    prev_highs=prev_highs, **BASE)
    assert not any(t["exit_reason"] == "Partial TP" for t in res["trades"]), \
        "con la ganancia mínima no alcanzada, el fade no dispara"
    skips = res["trades"][-1]["partials_skipped"]
    assert skips == [{"index": 0, "reason": "min_gain"}]


def test_nivel_ya_cruzado_al_entrar_se_salta():
    closes = [10, 12, 14, 19.8, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5]
    close, open_, high, low, entries, exits = _day(closes)
    prev_highs = _prev_highs_from(high)
    pts = [{"distance_pct": 0.30, "capital_pct": 0.5,
            "fade_from_high_pct": 0.50, "min_gain_pct": None, "priority": 0}]
    res = _simulate(False, close=close, open_=open_, high=high, low=low,
                    entries=entries, exits=exits, partial_take_profits=pts,
                    prev_highs=prev_highs, **BASE)
    assert not any(str(t["exit_reason"]).startswith("Partial TP") for t in res["trades"])
    assert res["trades"][-1]["partials_skipped"] == [{"index": 0, "reason": "crossed"}]


def test_oco_misma_vela_la_prioridad_decide():
    """Una vela toca los dos niveles (15.2 y 10): manda el elegido, no se suman."""
    closes = [10, 12, 14, 19.8, 16, 15.9, 15.8, 15.7, 15.6, 11, 11]
    lows = [9.8, 11.8, 13.8, 19.6, 15.8, 15.7, 15.6, 15.5, 15.4, 9.5, 9.5]
    close, open_, high, low, entries, exits = _day(closes, lows=lows)
    prev_highs = _prev_highs_from(high)
    base_pts = {"distance_pct": 0.05, "capital_pct": 0.5,
                "fade_from_high_pct": 0.50, "min_gain_pct": None}

    r_fade = _simulate(False, close=close, open_=open_, high=high, low=low,
                        entries=entries, exits=exits, prev_highs=prev_highs,
                        partial_take_profits=[dict(base_pts, priority=0)], **BASE)
    r_entry = _simulate(False, close=close, open_=open_, high=high, low=low,
                        entries=entries, exits=exits, prev_highs=prev_highs,
                        partial_take_profits=[dict(base_pts, priority=1)], **BASE)

    pf = [t for t in r_fade["trades"] if t["exit_reason"] == "Partial TP (Fade)"]
    pe = [t for t in r_entry["trades"] if t["exit_reason"] == "Partial TP (Entrada)"]
    assert len(pf) == 1 and len(pe) == 1, "una sola ejecución por slot (OCO)"
    assert pf[0]["exit_price"] == pytest.approx(10.0), "priority=fade → nivel 10"
    assert pe[0]["exit_price"] == pytest.approx(15.2), "priority=entry → nivel 15.2"
    # mismo capital en ambos casos (nunca suman)
    assert pf[0]["size"] == pytest.approx(pe[0]["size"])


def test_sin_fade_comportamiento_historico():
    """Sin campos 1A, el parcial % desde entrada funciona como siempre."""
    closes = [10, 12, 14, 19.8, 16, 15.5, 14, 12, 10.5, 9.9, 9.9]
    close, open_, high, low, entries, exits = _day(closes)
    prev_highs = _prev_highs_from(high)
    pts = [{"distance_pct": 0.05, "capital_pct": 0.5}]
    res = _simulate(False, close=close, open_=open_, high=high, low=low,
                    entries=entries, exits=exits, partial_take_profits=pts,
                    prev_highs=prev_highs, **BASE)
    p = [t for t in res["trades"] if t["exit_reason"] == "Partial TP"]
    assert len(p) == 1 and p[0]["exit_price"] == pytest.approx(15.2)
    assert res["trades"][-1]["partials_skipped"] == []


def test_mae_mfe_desde_maximo_previo_short():
    """MFE_prev = fade máximo desde el máximo; MAE_prev = repunte sobre el máximo."""
    closes = [10, 12, 14, 18, 16, 17.5, 14, 12, 10.5, 9.9, 9.9]
    close, open_, high, low, entries, exits = _day(closes)
    prev_highs = _prev_highs_from(high)
    res = _simulate(False, close=close, open_=open_, high=high, low=low,
                    entries=entries, exits=exits, partial_take_profits=None,
                    prev_highs=prev_highs, **BASE)
    t = res["trades"][0]
    assert t["prev_max_ref"] == pytest.approx(18.2)  # high acumulado hasta bar 3
    lo = min(low[4:])            # 9.7 aprox según lows por defecto
    hi = max(high[4:])
    assert t["mfe_prev_max"] == pytest.approx((18.2 - lo) / 18.2 * 100, abs=1e-3)
    assert t["mae_prev_max"] == pytest.approx((hi - 18.2) / 18.2 * 100, abs=1e-3)


def test_fila_condicional_parser_y_capital_por_disparo():
    """Formato UI nuevo: fila % + fila condicional fade (sin distance_pct).
    El parser las empareja en UN slot; el disparo usa el capital de SU fila."""
    from app.services.strategy_engine import _parse_partial_tps
    risk = {"partial_take_profits": [
        {"distance_pct": 5, "capital_pct": 50},
        {"distance_pct": None, "fade_from_high_pct": 50, "min_gain_pct": None,
         "priority": "fade", "capital_pct": 30},
    ]}
    pts = _parse_partial_tps(risk)
    assert pts is not None and len(pts) == 1, "la fila fade se empareja con la % anterior"
    slot = pts[0]
    assert slot["distance_pct"] == pytest.approx(0.05)
    assert slot["capital_pct"] == pytest.approx(0.5)
    assert slot["capital_pct_a"] == pytest.approx(0.3), "capital de la fila fade"
    assert slot["fade_from_high_pct"] == pytest.approx(0.5)

    # Fade huérfano (sin fila % encima): slot fade puro con 1B inalcanzable.
    risk2 = {"partial_take_profits": [
        {"distance_pct": None, "fade_from_high_pct": 40, "capital_pct": 25},
    ]}
    pts2 = _parse_partial_tps(risk2)
    assert len(pts2) == 1 and pts2[0]["fade_from_high_pct"] == pytest.approx(0.4)
    assert pts2[0]["distance_pct"] == pytest.approx(0.99), "1B inalcanzable (±99%)"

    # Formato de fila autocontenida (UI nueva): fade + fallback % de entrada.
    risk3 = {"partial_take_profits": [
        {"distance_pct": None, "fade_from_high_pct": 50, "fallback_entry_pct": 5,
         "min_gain_pct": 10, "priority": "fade", "capital_pct": 40},
    ]}
    pts3 = _parse_partial_tps(risk3)
    assert len(pts3) == 1
    assert pts3[0]["distance_pct"] == pytest.approx(0.05), "respaldo % desde entrada"
    assert pts3[0]["fade_from_high_pct"] == pytest.approx(0.5)
    assert pts3[0]["capital_pct"] == pytest.approx(0.4)
    assert pts3[0]["capital_pct_a"] == pytest.approx(0.4), "un solo capital para ambos disparos"

    # Simulación: gana el fade → vende el 30% (capital de la fila condicional).
    closes = [10, 12, 14, 19.8, 16, 15.9, 15.8, 15.7, 15.6, 11, 11]
    lows = [9.8, 11.8, 13.8, 19.6, 15.8, 15.7, 15.6, 15.5, 15.4, 9.5, 9.5]
    close, open_, high, low, entries, exits = _day(closes, lows=lows)
    prev_highs = _prev_highs_from(high)
    res = _simulate(False, close=close, open_=open_, high=high, low=low,
                    entries=entries, exits=exits, partial_take_profits=pts,
                    prev_highs=prev_highs, **BASE)
    p = [t for t in res["trades"] if t["exit_reason"] == "Partial TP (Fade)"][0]
    total_size = res["trades"][-1]["size"] + p["size"]
    assert p["exit_price"] == pytest.approx(10.0), "gana el fade (misma vela, manda fade)"
    assert p["size"] == pytest.approx(total_size * 0.30), "vende el capital de la fila fade"


@pytest.mark.parametrize("use_jit", [False, True])
def test_paridad_legacy_jit_con_fade(use_jit):
    closes = [10, 12, 14, 18, 16, 15.5, 14, 12, 10.5, 9.9, 9.9]
    close, open_, high, low, entries, exits = _day(closes)
    prev_highs = _prev_highs_from(high)
    pts = [{"distance_pct": 0.05, "capital_pct": 0.5,
            "fade_from_high_pct": 0.50, "min_gain_pct": 0.10, "priority": 0}]
    res = _simulate(use_jit, close=close, open_=open_, high=high, low=low,
                    entries=entries, exits=exits, partial_take_profits=pts,
                    prev_highs=prev_highs, **BASE)
    for t in res["trades"]:
        assert t["prev_max_ref"] == pytest.approx(18.2)
        assert "mae_prev_max" in t and "mfe_prev_max" in t and "fade_at_entry_pct" in t
    partials = [t for t in res["trades"] if t["exit_reason"] == "Partial TP (Entrada)"]
    assert len(partials) == 1, "1B (15.2) se toca antes que el fade (9.1) -> gana Entrada"
