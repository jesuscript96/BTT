"""Picos y valles enumerados (PRD 2026-09-18, §8) — los 8 tests exigibles.

Familia "Pico" / "Edad del pico" / "Volumen del pico": el mismo giro que
"Ultimo pivote", pero guardando los últimos M del día en un búfer circular e
indexando por EVENTOS (`pivot_rank`), no por velas. Es lo que permite expresar
un hombro-cabeza-hombro comparando rank 1 contra rank 2 y rank 3.

Datos 100% sintéticos, al estilo de test_n2a_native_equivalence.py — no toca
DuckDB ni GCS. FASE 1 del PRD: la familia NO está en _RAW_INDICATOR_DISPATCH
(eso lo cubre el test extra del final, no hace falta paridad con el carril
nativo porque nunca va por él).
"""
import time

import numpy as np
import pandas as pd
import pytest

from app.services.indicators import compute_indicator
from app.services.strategy_engine import (
    _RAW_INDICATOR_DISPATCH,
    compile_strategy_def,
    translate_strategy,
)


# ─── Datos sintéticos ─────────────────────────────────────────────────────

def _dia_giros(date="2024-11-12", offset=0.0):
    """Día con TRES techos y DOS suelos de precios distinguibles (win=2).

    high = [10, 10.5, 12, 11, 10, 9, 9.5, 10.8, 13, 12, 11, 9, 8.5, 9, 9.8,
            10.5, 9.5, 9, 8.8] (+ offset)
    low  = high - 0.30, así que los suelos son los mínimos del mismo camino.

    Con pivot_window=2:
      techos (índice, precio): (2, 12.0), (8, 13.0), (15, 10.5)
        → confirmados en las barras 4, 10 y 17 (= índice + win)
      suelos  (índice, precio): (5, 8.7), (12, 8.2)
        → confirmados en las barras 7 y 14
    El volumen de cada vela es distinguible: v[i] = (i+1) * 1000.
    """
    highs = np.array([10, 10.5, 12, 11, 10, 9, 9.5, 10.8, 13, 12, 11, 9, 8.5,
                      9, 9.8, 10.5, 9.5, 9, 8.8], dtype=float) + offset
    n = len(highs)
    ts = pd.date_range(f"{date} 09:30", periods=n, freq="1min")
    return pd.DataFrame({
        "timestamp": ts,
        "open": highs - 0.10,
        "high": highs,
        "low": highs - 0.30,
        "close": highs - 0.20,
        "volume": np.arange(1, n + 1) * 1000.0,
    })


def _dia_aleatorio(seed=7, n=400, date="2024-11-12", start="04:00"):
    """Random walk 1m con huecos de minutos (premarket ilíquido realista)."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(f"{date} {start}", periods=n, freq="1min")
    minutes = ts.hour * 60 + ts.minute
    ts = ts[~((minutes % 7) == 3)]
    n = len(ts)
    close = np.maximum(10.0 + np.cumsum(rng.normal(0, 0.08, n)), 1.0)
    spread = np.abs(rng.normal(0, 0.04, n))
    open_ = close + rng.normal(0, 0.02, n)
    return pd.DataFrame({
        "timestamp": ts,
        "open": open_,
        "high": np.maximum(open_, close) + spread,
        "low": np.minimum(open_, close) - spread,
        "close": close,
        "volume": rng.integers(100, 50_000, n).astype(np.int64),
    })


# ─── Constructores de estrategia (patrón del test_n2a_native_equivalence) ──

def _strategy(entry_conds):
    return {
        "bias": "long",
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {"operator": "AND", "conditions": entry_conds},
            "entry_time_windows": [],
        },
        "exit_logic": {
            "timeframe": "1m",
            "root_condition": {"operator": "AND", "conditions": [
                {"type": "indicator_comparison",
                 "source": {"name": "Close"}, "comparator": "GREATER_THAN",
                 "target": 1e12},   # nunca: aquí solo interesan las entries
            ]},
        },
        "risk_management": {
            "use_hard_stop": True,
            "hard_stop": {"type": "Percentage", "value": 5},
        },
    }


def _cmp(source, comparator, target):
    return {"type": "indicator_comparison", "source": source,
            "comparator": comparator, "target": target}


def _entries(df, source, comparator, target):
    strat = _strategy([_cmp(source, comparator, target)])
    compiled = compile_strategy_def(strat)
    sig = translate_strategy(df.copy(), strat, compiled=compiled)
    return np.asarray(sig["entries"], dtype=bool)


# ─── 1. Paridad con lo que ya hay ─────────────────────────────────────────

@pytest.mark.parametrize("swing_dir", ["up", "down"])
@pytest.mark.parametrize("win", [3, 5])
def test_1_paridad_con_ultimo_pivote(swing_dir, win):
    """Pico(rank=1) ≡ Ultimo pivote, mismos swing_dir y pivot_window,
    tolerancia 0 (NaN por NaN incluido)."""
    df = _dia_aleatorio(seed=7)
    pico = compute_indicator(
        "Pico", df, swing_dir=swing_dir, pivot_window=win, pivot_rank=1
    ).to_numpy()
    ultimo = compute_indicator(
        "Ultimo pivote", df, swing_dir=swing_dir, pivot_window=win
    ).to_numpy()
    assert np.isfinite(pico).any(), "caso trivial: el día no genera ningún pivote"
    assert np.array_equal(pico, ultimo, equal_nan=True), (
        f"rank=1 diverge de Ultimo pivote (swing_dir={swing_dir}, win={win}): "
        f"primeras diffs={np.flatnonzero(~((pico == ultimo) | (np.isnan(pico) & np.isnan(ultimo))))[:10]}"
    )


# ─── 2. Orden correcto ────────────────────────────────────────────────────

def test_2_orden_de_los_giros():
    """Con giros conocidos (12 → 13 → 10.5), rank 1/2/3 devuelven los tres
    techos esperados Y en el orden correcto: 1 = el último (10.5), 2 = el
    anterior (13), 3 = el de antes (12)."""
    df = _dia_giros()
    kw = {"swing_dir": "up", "pivot_window": 2}
    r1 = compute_indicator("Pico", df, pivot_rank=1, **kw).to_numpy()
    r2 = compute_indicator("Pico", df, pivot_rank=2, **kw).to_numpy()
    r3 = compute_indicator("Pico", df, pivot_rank=3, **kw).to_numpy()

    # confirmaciones en las barras 4, 10 y 17 (pivote en i, confirmado en i+win)
    assert np.isnan(r1[:4]).all()
    assert (r1[4:10] == 12.0).all()
    assert (r1[10:17] == 13.0).all()
    assert (r1[17:] == 10.5).all()

    assert np.isnan(r2[:10]).all()
    assert (r2[10:17] == 12.0).all()
    assert (r2[17:] == 13.0).all()

    assert np.isnan(r3[:17]).all()
    assert (r3[17:] == 12.0).all()

    # valles (swing_dir="down"): suelos en (5, 8.7) y (12, 8.2)
    v1 = compute_indicator("Pico", df, swing_dir="down", pivot_window=2,
                           pivot_rank=1).to_numpy()
    v2 = compute_indicator("Pico", df, swing_dir="down", pivot_window=2,
                           pivot_rank=2).to_numpy()
    assert np.isnan(v1[:7]).all()
    assert (v1[7:14] == 8.7).all()
    assert (v1[14:] == 8.2).all()
    assert np.isnan(v2[:14]).all()
    assert (v2[14:] == 8.7).all()

    # edad y volumen del rank 3 en la barra 17: el techo de 12 está en la
    # barra 2 (15 minutos atrás, volumen 3*1000)
    edad = compute_indicator("Edad del pico", df, pivot_rank=3, **kw).to_numpy()
    vol = compute_indicator("Volumen del pico", df, pivot_rank=3, **kw).to_numpy()
    assert edad[17] == 15.0
    assert vol[17] == 3000.0


# ─── 3. Sin lookahead ─────────────────────────────────────────────────────

@pytest.mark.parametrize("nombre", ["Pico", "Edad del pico", "Volumen del pico"])
def test_3_sin_lookahead(nombre):
    """Para cada barra t, lo calculado sobre df[:t+1] es idéntico a lo
    calculado sobre el día entero. Innegociable, y para los tres indicadores
    de la familia (PRD §8.3)."""
    df = _dia_aleatorio(seed=13, n=240)
    kw = {"swing_dir": "up", "pivot_window": 3, "pivot_rank": 2}
    full = compute_indicator(nombre, df, **kw).to_numpy()
    for t in range(len(df)):
        sub = compute_indicator(nombre, df.iloc[: t + 1], **kw).to_numpy()
        a, b = full[t], sub[-1]
        assert (a == b) or (np.isnan(a) and np.isnan(b)), (
            f"{nombre}: lookahead en la barra {t}: entero={a!r} parcial={b!r}"
        )


# ─── 4. NaN honesto ───────────────────────────────────────────────────────

def test_4_nan_honesto():
    """Con menos de pivot_rank giros confirmados el valor es NaN y la
    condición NO dispara. Incluye el arranque del día (rank=1)."""
    df = _dia_giros()
    kw = {"swing_dir": "up", "pivot_window": 2}

    # arranque del día: ni rank=1 existe hasta la barra 4
    r1 = compute_indicator("Pico", df, pivot_rank=1, **kw).to_numpy()
    assert np.isnan(r1[:4]).all()

    # rank=2 no existe hasta la barra 10 (segundo techo confirmado)
    r2 = compute_indicator("Pico", df, pivot_rank=2, **kw).to_numpy()
    assert np.isnan(r2[:10]).all()
    assert np.isfinite(r2[10:]).all()

    # y la condición no dispara mientras vale NaN (NaN > -1e9 es False)
    src = {"name": "Pico", "swing_dir": "up", "pivot_window": 2, "pivot_rank": 2}
    entries = _entries(df, src, "GREATER_THAN", -1e9)
    assert not entries[:10].any(), "entradas con el rank aún en NaN"
    assert entries[10:].all(), "el rank ya confirmado debería disparar"


# ─── 5. Reinicio diario ───────────────────────────────────────────────────

def test_5_reinicio_diario():
    """Frame de dos días: el primer giro del día 2 no hereda nada del día 1."""
    d1 = _dia_giros(date="2024-11-12")               # techos 12, 13, 10.5
    d2 = _dia_giros(date="2024-11-13", offset=5.0)   # techos 17, 18, 15.5
    df = pd.concat([d1, d2], ignore_index=True)
    n1 = len(d1)                                     # 19: el día 2 empieza en la barra 19

    kw = {"swing_dir": "up", "pivot_window": 2}
    r1 = compute_indicator("Pico", df, pivot_rank=1, **kw).to_numpy()
    r2 = compute_indicator("Pico", df, pivot_rank=2, **kw).to_numpy()

    # día 2: rank=1 no aparece hasta SU primer techo (local 2 + win → global 23)
    assert np.isnan(r1[n1 : n1 + 4]).all(), "rank=1 nace antes del primer giro del día 2"
    assert (r1[n1 + 4 : n1 + 10] == 17.0).all()

    # rank=2 tras el primer techo del día 2: NaN. Si heredara del día 1,
    # valdría 10.5 (el último techo del día 1).
    assert np.isnan(r2[n1 + 4 : n1 + 10]).all(), (
        f"el día 2 hereda pivotes del día 1: {r2[n1 + 4 : n1 + 10]}"
    )
    # y a partir del segundo techo del día 2, rank=2 es el PRIMERO del día 2
    # (17.0), y tras confirmarse el tercero (barra global n1+17) pasa a 18.0
    assert (r2[n1 + 10 : n1 + 17] == 17.0).all()
    assert (r2[n1 + 17 :] == 18.0).all()


# ─── 6. Empates ───────────────────────────────────────────────────────────

def test_6_empates_tramo_plano():
    """Tramo plano → ningún pivote nuevo (comparación estricta): todo NaN."""
    n = 60
    ts = pd.date_range("2024-11-12 09:30", periods=n, freq="1min")
    df = pd.DataFrame({
        "timestamp": ts,
        "open": np.full(n, 9.9), "high": np.full(n, 10.0),
        "low": np.full(n, 9.7), "close": np.full(n, 9.8),
        "volume": np.full(n, 1000.0),
    })
    for swing_dir in ("up", "down"):
        serie = compute_indicator("Pico", df, swing_dir=swing_dir,
                                  pivot_window=2, pivot_rank=1).to_numpy()
        assert np.isnan(serie).all(), (
            f"un tramo plano generó pivotes con swing_dir={swing_dir}"
        )


# ─── 7. pivot_rank viaja entero ───────────────────────────────────────────

def test_7_pivot_rank_viaja_entero():
    """Una estrategia con rank=1 y otra con rank=2 dan señales distintas. Es
    el test que caza el fallo de la clave de caché del §5.2: si pivot_rank no
    entrara en la clave, rank=1 y rank=2 devolverían el MISMO array y el
    patrón daría siempre verdadero."""
    df = _dia_giros()
    kw = {"swing_dir": "up", "pivot_window": 2}

    # (a) la clave de caché: mismo dict, dos ranks → dos arrays distintos
    cache = {}
    r1 = compute_indicator("Pico", df, pivot_rank=1, cache=cache, **kw).to_numpy()
    r2 = compute_indicator("Pico", df, pivot_rank=2, cache=cache, **kw).to_numpy()
    assert not np.array_equal(r1, r2, equal_nan=True), (
        "rank=1 y rank=2 comparten caché: pivot_rank no entra en la clave"
    )

    # (b) a nivel de estrategia (pasa por _compute_from_config): el rank 1
    # llega a 10.5 (cruza 11) y el rank 2 se queda en 12/13 (nunca cruza)
    src1 = {"name": "Pico", "swing_dir": "up", "pivot_window": 2, "pivot_rank": 1}
    src2 = {"name": "Pico", "swing_dir": "up", "pivot_window": 2, "pivot_rank": 2}
    e1 = _entries(df, src1, "LESS_THAN", 11.0)
    e2 = _entries(df, src2, "LESS_THAN", 11.0)
    assert e1[17:].all() and not e1[:17].any()
    assert not e2.any()
    assert not np.array_equal(e1, e2), "rank=1 y rank=2 dan las mismas señales"


# ─── 8. Coste ─────────────────────────────────────────────────────────────

def test_8_coste_no_depende_de_pivot_window():
    """El tiempo del indicador no depende de pivot_window (confirmación de la
    medición del §7 del PRD: w=3, 5 y 10 valen lo mismo)."""
    df = _dia_aleatorio(seed=21, n=960)

    def _mide(win):
        compute_indicator("Pico", df, swing_dir="up", pivot_window=win,
                          pivot_rank=2)  # warm-up (incluye compilar numba)
        mejores = []
        for _ in range(5):
            t0 = time.perf_counter()
            for _ in range(20):
                compute_indicator("Pico", df, swing_dir="up",
                                  pivot_window=win, pivot_rank=2)
            mejores.append((time.perf_counter() - t0) / 20)
        return min(mejores)

    c3, c5, c10 = _mide(3), _mide(5), _mide(10)
    ratio = max(c3, c5, c10) / min(c3, c5, c10)
    assert ratio < 3.0, (
        f"el coste depende de pivot_window: 3={c3 * 1e3:.2f}ms "
        f"5={c5 * 1e3:.2f}ms 10={c10 * 1e3:.2f}ms (ratio {ratio:.1f})"
    )


# ─── Extra (fuera de los 8): Fase 1 = carril legacy ───────────────────────

def test_fase1_la_familia_va_por_el_carril_legacy():
    """PRD §7.1, Fase 1: la familia NO se registra en _RAW_INDICATOR_DISPATCH
    y cualquier estrategia que la use cae al carril legacy por el gate
    has_special (que es donde pivot_rank viaja entero). El día que se mueva
    al dispatch nativo hay que ampliar ANTES la clave de deduplicación de
    _extract_indicator_plan (trampa del §7.1)."""
    for nombre in ("Pico", "Edad del pico", "Volumen del pico"):
        assert nombre not in _RAW_INDICATOR_DISPATCH, (
            f"{nombre} está en el dispatch nativo: eso es la Fase 2 del PRD, "
            "no la Fase 1"
        )
        src = {"name": nombre, "swing_dir": "up", "pivot_window": 3,
               "pivot_rank": 1}
        strat = _strategy([_cmp(src, "GREATER_THAN", -1e9)])
        plan = compile_strategy_def(strat)["_indicator_plan"]
        assert plan["has_special"], f"{nombre} no cae al carril legacy"
