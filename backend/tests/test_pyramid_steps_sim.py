"""CAMINO DE CONDICIONES en piramidación — P1: el simulador
(PRD 2026-09-16, docs/PRD_CAMINITO_CONDICIONES_PIRAMIDACION_20260916.md §8 y §11).

Llama a `simulate` directamente con velas sintéticas: cada test fija la
semántica EXACTA del camino (orden de enganche, Q2/Q3/Q4, same_bar, rearme,
invariante sequential, ventana horaria, look-ahead y lot_stop). La regresión
dorada de las corridas SIN camino vive en test_lot_stop_sim.py (mismo hash
congelado) y sigue pasando junto a esta suite.
"""
import numpy as np
import pandas as pd

from app.services.portfolio_sim import simulate
from app.services.strategy_engine import (
    aplica_ventana_relleno_nivel, mapa_senales_nivel,
)

RISK = 100.0      # FIXED: 100 $ por trade → 10 acciones a 10 $
CASH = 10000.0
N = 20


def _dia(n=N, precio=None, highs_puntual=None):
    """Velas planas a `precio`; `highs_puntual` = {bar: high} para pintar mechas."""
    p = precio if precio is not None else 10.0
    open_ = np.full(n, p)
    close = np.full(n, p)
    high = np.full(n, p + 0.05)
    low = np.full(n, p - 0.05)
    for i, h in (highs_puntual or {}).items():
        high[i] = h
    ts = pd.date_range("2026-09-16 04:00", periods=n, freq="1min")
    ts_ns = ts.values.astype("datetime64[ns]").astype(np.int64)
    return open_, high, low, close, ts_ns


def _senal(*barras, n=N):
    s = np.zeros(n, dtype=bool)
    for b in barras:
        s[b] = True
    return s


def _senal_rango(desde, hasta, n=N):
    s = np.zeros(n, dtype=bool)
    s[desde:hasta + 1] = True
    return s


def _nivel_camino(pasos, same_bar=True, **kw):
    """Nivel-camino add en dólares fijos: 100 $ a 10 = 10 acc por disparo."""
    nv = {
        "steps_signals": pasos, "same_bar": same_bar, "action": "add",
        "capital_frac": 0.0, "max_fires": kw.pop("max_fires", 2),
        "unit": "usd", "amount_usd": kw.pop("amount_usd", 100.0),
        "size_by_sl": False, "hybrid_stop": False,
        "hybrid_black_swan_pct": None, "hybrid_max_loss_pct": None,
    }
    if kw.pop("lot_stop", None) is not None:
        nv["lot_stop"] = kw.pop("_lot_stop_def")
    nv.update(kw)
    return nv


def _nivel_normal(senal, **kw):
    nv = {
        "signals": senal, "action": "add", "capital_frac": 0.0,
        "max_fires": kw.pop("max_fires", 2), "unit": "usd",
        "amount_usd": kw.pop("amount_usd", 100.0), "size_by_sl": False,
        "hybrid_stop": False, "hybrid_black_swan_pct": None,
        "hybrid_max_loss_pct": None,
    }
    nv.update(kw)
    return nv


def _correr(open_, high, low, close, ts_ns, entries, exits, niveles,
            direction="shortonly", **kw):
    # hods/lods/previos como los pasa el caller real (`_compute_signals_for_pair`)
    hods = np.maximum.accumulate(high)
    lods = np.minimum.accumulate(low)
    prev_h = np.empty_like(hods); prev_h[0] = high[0]; prev_h[1:] = hods[:-1]
    prev_l = np.empty_like(lods); prev_l[0] = low[0]; prev_l[1:] = lods[:-1]
    params = dict(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction=direction,
        init_cash=CASH, risk_r=RISK, risk_type="FIXED",
        fees=0.0, fee_type="PERCENT", slippage=0.0,
        look_ahead_prevention=True,
        pyramid_levels=niveles, pyramid_sequential=False,
        timestamps=ts_ns,
        hods=hods, lods=lods, prev_highs=prev_h, prev_lows=prev_l,
    )
    params.update(kw)
    return simulate(**params)


def _adds(res):
    """Los `add` de la bitácora de pirámide de todos los trades."""
    out = []
    for t in res["trades"]:
        for e in (t.get("pyr_executions") or []):
            if e["kind"] == "add":
                out.append(e)
    return out


# ── §11-1: orden de enganche ───────────────────────────────────────────────

def test_B_antes_que_A_no_dispara_y_A_entonces_B_si():
    """A@5, B@8. Camino [A,B] dispara al enganchar B; camino [B,A] no dispara
    nunca: el evento de A (barra 5) fue ANTES de su turno y un paso futuro
    no consume su flanco."""
    def run(pasos):
        open_, high, low, close, ts = _dia()
        res = _correr(open_, high, low, close, ts, _senal(1), _senal(15),
                      [pasos])
        return [(a["idx"], a["size"]) for a in _adds(res)]

    sigA, sigB = _senal(5), _senal(8)
    assert run(_nivel_camino([sigA, sigB], max_fires=1)) == [(9, 10.0)]
    assert run(_nivel_camino([sigB, sigA], max_fires=1)) == []


# ── §11-2: condición sostenida al entrar (Q2=A) ────────────────────────────

def test_condicion_vigente_al_entrar_engancha_en_la_primera_vela():
    """A está SIEMPRE cierta (ya lo estaba al entrar): su prev arranca False
    en cada entrada, así que engancha en la primera vela post-entrada y el
    camino dispara cuando llega B (barra 8)."""
    open_, high, low, close, ts = _dia()
    niveles = [_nivel_camino([_senal_rango(0, N - 1), _senal(8)], max_fires=1)]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(15), niveles)
    assert [(a["idx"], a["size"]) for a in _adds(res)] == [(9, 10.0)]


# ── §11-3: evento transitorio previo a la entrada NO cuenta (Q2=A) ────────

def test_evento_transitorio_previo_a_la_entrada_no_cuenta():
    """A solo fue cierta en la barra 0, ANTES de entrar (fill en la 2): no
    engancha jamás y el camino no dispara aunque B llegue."""
    open_, high, low, close, ts = _dia()
    niveles = [_nivel_camino([_senal(0), _senal(8)], max_fires=1)]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(15), niveles)
    assert _adds(res) == []


# ── §11-4: same_bar=True generaliza el AND ────────────────────────────────

def test_same_bar_true_es_el_AND_de_hoy():
    """A y B en la MISMA vela (5): el camino dispara esa vela y llena en la
    6, exactamente como un nivel normal cuya señal es A AND B."""
    open_, high, low, close, ts = _dia()
    camino = _correr(open_, high, low, close, ts, _senal(1), _senal(15),
                     [_nivel_camino([_senal(5), _senal(5)], max_fires=1)])
    and_clasico = _correr(open_, high, low, close, ts, _senal(1), _senal(15),
                          [_nivel_normal(_senal(5), max_fires=1)])
    assert [(a["idx"], a["price"], a["size"]) for a in _adds(camino)] == \
        [(a["idx"], a["price"], a["size"]) for a in _adds(and_clasico)] == \
        [(6, 10.0, 10.0)]


# ── §11-5: same_bar=False exige >=1 vela entre enganches ──────────────────

def test_same_bar_false_no_completa_en_la_misma_vela():
    def run(sigB):
        open_, high, low, close, ts = _dia()
        res = _correr(open_, high, low, close, ts, _senal(1), _senal(15),
                      [_nivel_camino([_senal(5), sigB], same_bar=False,
                                     max_fires=1)])
        return [(a["idx"], a["size"]) for a in _adds(res)]

    assert run(_senal(5)) == []          # B en la MISMA vela: bloqueada
    assert run(_senal(6)) == [(7, 10.0)]  # B en i+1: dispara y llena en la 7


# ── §11-6: times=2 recorre el camino dos veces (Q4) y Q3 ─────────────────

def test_times_2_recorre_el_camino_dos_veces():
    """A con DOS flancos (3-5 y 9-14), B en la 5 y en la 11: dos disparos,
    cada uno tras recorrer el camino ENTERO (Q4)."""
    n = 20
    sigA = _senal_rango(3, 5, n=n)
    sigA[9:15] = True
    sigB = _senal(5, 11, n=n)
    open_, high, low, close, ts = _dia(n=n)
    res = _correr(open_, high, low, close, ts, _senal(1, n=n), _senal(17, n=n),
                  [_nivel_camino([sigA, sigB], max_fires=2)])
    assert [(a["idx"], a["size"]) for a in _adds(res)] == [(6, 10.0), (12, 10.0)]


def test_tras_disparar_la_condicion_sostenida_no_redispara():
    """Q3: A sostenida y B sostenido tras el primer disparo → NO hay segundo
    disparo sin flancos nuevos, aunque queden `times`."""
    n = 20
    niveles = [_nivel_camino([_senal_rango(3, 12, n=n), _senal_rango(4, 12, n=n)],
                             max_fires=2)]
    open_, high, low, close, ts = _dia(n=n)
    res = _correr(open_, high, low, close, ts, _senal(1, n=n), _senal(17, n=n), niveles)
    assert [(a["idx"], a["size"]) for a in _adds(res)] == [(5, 10.0)]


# ── §11-7: rearme en reentrada ─────────────────────────────────────────────

def test_la_reentrada_rearma_el_camino():
    """A sostenida TODO el día. Trade 1: dispara (B@6). Sin rearme, el prev
    de A seguiría True y el trade 2 no podría enganchar A jamás; CON rearme,
    A engancha en la primera vela del segundo trade y B@27 vuelve a disparar."""
    n = 36
    entries = _senal(1, 20, n=n)   # dos entradas (con salida en la 12)
    exits = _senal(12, 32, n=n)
    niveles = [_nivel_camino([_senal_rango(0, n - 1, n=n), _senal(6, 27, n=n)],
                             max_fires=1)]
    open_, high, low, close, ts = _dia(n=n)
    res = _correr(open_, high, low, close, ts, entries, exits, niveles,
                  accumulate=True)
    adds = [(a["idx"], a["size"]) for a in _adds(res)]
    assert adds == [(7, 10.0), (28, 10.0)]   # uno por trade


# ── §11-8: camino que nunca completa B ────────────────────────────────────

def test_camino_que_nunca_completa_b_cero_anadidos_sin_crash():
    open_, high, low, close, ts = _dia()
    niveles = [_nivel_camino([_senal(5), _senal()], max_fires=3)]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(15), niveles)
    assert _adds(res) == []
    final = [t for t in res["trades"] if t["exit_reason"] == "Signal"]
    assert len(final) == 1 and final[0]["size"] == 10.0   # solo la base


# ── §11-9: invariante sequential entre niveles ────────────────────────────

def test_camino_a_medias_ocupa_el_turno_y_bloquea_al_siguiente():
    """Nivel 1 = camino [A@4, B@12] (a medias hasta la 12); nivel 2 = normal
    con señal en la 6. En SECUENCIAL el nivel 2 no tiene el turno hasta que
    el camino dispare: su evento de la 6 no se consume y solo dispara con un
    flanco NUEVO (la 15). Nada de adds en la 7."""
    n = 24
    niveles = [
        _nivel_camino([_senal(4, n=n), _senal(12, n=n)], max_fires=1),
        _nivel_normal(_senal(15, n=n), max_fires=1),
    ]
    open_, high, low, close, ts = _dia(n=n)
    res = _correr(open_, high, low, close, ts, _senal(1, n=n), _senal(20, n=n),
                  niveles, pyramid_sequential=True)
    adds = [(a["level"], a["idx"], a["size"]) for a in _adds(res)]
    assert adds == [(1, 13, 10.0), (2, 16, 10.0)]
    assert all(a["idx"] != 7 for a in _adds(res))


# ── §11-10: ventana horaria, fin a fin (evaluador + simulador) ────────────

def test_la_ventana_de_entradas_apaga_los_pasos_fuera():
    """Paso 2 solo se cumple en la barra 15 (11 $). Sin ventana, dispara y
    llena en la 16; con ventana 04:00-04:10, la señal del paso queda
    enmascarada, el paso no engancha y no hay añadido."""
    from app.services.strategy_engine import compile_strategy_def, translate_strategy

    def _corre(ventanas):
        n = 20
        ts = pd.date_range("2026-09-16 04:00", periods=n, freq="1min")
        close = np.full(n, 10.0); close[15] = 11.0
        frame = pd.DataFrame({
            "timestamp": ts, "open": np.full(n, 10.0),
            "high": np.maximum(np.full(n, 10.0), close) + 0.05,
            "low": np.full(n, 9.95), "close": close,
            "volume": np.full(n, 1000.0),
        })
        siempre = {
            "type": "group", "operator": "AND",
            "conditions": [{
                "type": "indicator_comparison",
                "source": {"name": "Bar Close", "offset": 0},
                "comparator": "GREATER_THAN", "target": 0.0, "timeframe": "1m"}]}
        spike = {
            "type": "group", "operator": "AND",
            "conditions": [{
                "type": "indicator_comparison",
                "source": {"name": "Bar Close", "offset": 0},
                "comparator": "GREATER_THAN", "target": 10.5, "timeframe": "1m"}]}
        d = {
            "bias": "short",
            "entry_logic": {"timeframe": "1m", "root_condition": siempre,
                            **({"entry_time_windows": ventanas} if ventanas else {})},
            "exit_logic": {"timeframe": "1m",
                           "root_condition": {"type": "group", "operator": "AND",
                                              "conditions": []}},
            "risk_management": {"size_by_sl": False, "use_hard_stop": False},
            "pyramiding": {"timeframe": "1m", "mode": "individual", "levels": [
                {"times": 1, "same_bar": True, "steps": [siempre, spike],
                 "action": "add", "unit": "usd", "capital_pct": 100}]},
        }
        s = translate_strategy(frame, d, {}, compiled=compile_strategy_def(d))
        res = _correr(frame["open"].values, frame["high"].values,
                      frame["low"].values, close,
                      ts.values.astype("datetime64[ns]").astype(np.int64),
                      np.asarray(s["entries"]), np.asarray(s["exits"]),
                      s["pyramid_levels"])
        return [(a["idx"], a["size"]) for a in _adds(res)]

    assert _corre(None) == [(16, 10.0)]     # 100 $ a 10 → 10 acciones
    assert _corre([{"from_time": "04:00", "to_time": "04:10"}]) == []


# ── §11-11: look_ahead_prevention ─────────────────────────────────────────

def test_el_disparo_llena_en_la_apertura_de_la_siguiente_vela():
    """Camino que dispara en la 6: el add se ejecuta en la APERTURA de la 7
    (mismo `look_ahead_prevention` que entradas y pirámide de siempre)."""
    open_, high, low, close, ts = _dia()
    open_[7] = 9.5; close[7] = 9.5; low[7] = 9.45; high[7] = 9.55
    niveles = [_nivel_camino([_senal(5), _senal(6)], max_fires=1)]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(15), niveles)
    adds = _adds(res)
    assert len(adds) == 1
    assert adds[0]["idx"] == 7 and adds[0]["price"] == 9.5
    assert adds[0]["position_size"] == round(10.0 + 100.0 / 9.5, 6)


# ── §11-12: camino + lot_stop ──────────────────────────────────────────────

def test_el_lote_se_ancla_en_la_vela_de_senal_del_disparo():
    """Camino [A@3, B@4] con SL de lote HOD: el nivel se congela con el HOD
    de la vela de señal del AÑADIDO (la del disparo, barra 4) y una vela
    posterior con HOD mayor NO lo mueve — misma causalidad que el lote de un
    nivel normal."""
    open_, high, low, close, ts = _dia(highs_puntual={4: 10.2, 8: 10.3})
    niveles = [_nivel_camino([_senal(3), _senal(4)], max_fires=1,
                             lot_stop=True,
                             _lot_stop_def={"mode": "structure", "level": "hod",
                                            "offset_pct": 0.0})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(15), niveles)
    lotes = [t for t in res["trades"] if t["exit_reason"] == "Pyramid Lot Stop"]
    assert len(lotes) == 1
    leg = lotes[0]
    assert leg["stop_loss"] == 10.2          # HOD de la vela 4, no el de la 8
    assert leg["exit_price"] == 10.2         # min(10,2 ; high 10,3)
    assert leg["pnl"] == -2.0                # (10 − 10,2) × 10
    assert leg["entry_price"] == 10.0        # fill del add (apertura de la 5)


# ── Fontanería del pipeline (backtest_service / backtest_signals) ──────────

def _lv_normal():
    return {"signals": np.array([True, False, True]), "action": "add",
            "capital_frac": 0.05, "max_fires": 1, "unit": "pct",
            "amount_usd": 0.0, "size_by_sl": False, "hybrid_stop": False,
            "hybrid_black_swan_pct": None, "hybrid_max_loss_pct": None}


def _lv_camino():
    return {"steps_signals": [np.array([True, False, True]),
                              np.array([False, True, True])], "same_bar": True,
            "action": "add", "capital_frac": 0.05, "max_fires": 1,
            "unit": "pct", "amount_usd": 0.0, "size_by_sl": False,
            "hybrid_stop": False, "hybrid_black_swan_pct": None,
            "hybrid_max_loss_pct": None}


def test_mapa_senales_nivel_copia_o_recorta_todos_los_pasos():
    mask = np.array([True, False, True])
    out = mapa_senales_nivel(_lv_normal(), lambda s: s[mask])
    assert out["signals"].tolist() == [True, True]
    out = mapa_senales_nivel(_lv_camino(), lambda s: s[mask])
    assert [s.tolist() for s in out["steps_signals"]] == [[True, True], [False, True]]
    assert out["same_bar"] is True and out["action"] == "add"


def test_ventana_de_relleno_solo_al_ultimo_paso():
    """Los pasos intermedios no ejecutan nada: la regla de la vela de
    relleno les NO aplica; al último (cuyo enganche es el disparo), sí."""
    # velas 04:00-04:02, ventana hasta 04:01: el fill de una señal en la
    # 04:01 (la 02:00... 04:02) cae fuera → señal de la 04:01 apagada.
    minutes = np.array([240, 241, 242])
    tw = [{"from_time": "04:00", "to_time": "04:01"}]
    out = aplica_ventana_relleno_nivel(_lv_camino(), minutes, tw, True)
    # paso 1 INTACTO (no ejecuta nada); paso 2 (el disparo) filtrado
    assert out["steps_signals"][0].tolist() == [True, False, True]
    assert out["steps_signals"][1].tolist() == [False, False, False]
    # un nivel normal sigue siendo señal única con el mismo filtro
    out_n = aplica_ventana_relleno_nivel(_lv_normal(), minutes, tw, True)
    assert out_n["signals"].tolist() == [True, False, False]
