"""Picos y valles enumerados (PRD 2026-09-18, §8) — los 8 tests exigibles.

Familia "Pico" / "Edad del pico" / "Volumen del pico": el mismo giro que
"Ultimo pivote", pero guardando los últimos M del día en un búfer circular e
indexando por EVENTOS (`pivot_rank`), no por velas. Es lo que permite expresar
un hombro-cabeza-hombro comparando rank 1 contra rank 2 y rank 3.

Datos 100% sintéticos, al estilo de test_n2a_native_equivalence.py — no toca
DuckDB ni GCS. FASE 2 del PRD (§7.1): la familia ESTÁ en
_RAW_INDICATOR_DISPATCH y la paridad con el carril legacy se exige abajo
(clave de dedup, gate has_special y señales idénticas nativo↔legacy).
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
    translate_strategy_native,
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


# ─── Extra (fuera de los 8): Fase 2 = carril nativo ───────────────────────

def _make_arrays(df):
    """Réplica exacta de la construcción de arrays_native en
    backtest_signals._compute_signals_for_pair (test_n2a_native_equivalence)."""
    ts = pd.to_datetime(df["timestamp"])
    ts_int64 = ts.values.astype("datetime64[ns]").astype(np.int64)
    abs_min = ts_int64 // 60_000_000_000
    return {
        "open": np.asarray(df["open"], dtype=np.float64),
        "high": np.asarray(df["high"], dtype=np.float64),
        "low": np.asarray(df["low"], dtype=np.float64),
        "close": np.asarray(df["close"], dtype=np.float64),
        "volume": np.asarray(df["volume"], dtype=np.float64),
        "minutes_arr": abs_min % 1440,
        "abs_min_arr": abs_min,
    }


def _assert_equivalente_native(strat, df, min_entries=1):
    """Señales legacy vs nativo IDÉNTICAS (el legacy es LA especificación)."""
    compiled = compile_strategy_def(strat)
    assert not compiled["_indicator_plan"]["has_special"], (
        "la estrategia debería ser nativa-elegible y el gate la mandó a legacy"
    )
    legacy = translate_strategy(df.copy(), strat, {}, compiled=compiled)
    native = translate_strategy_native(_make_arrays(df), compiled, {})
    leg = np.asarray(legacy["entries"], dtype=bool)
    nat = np.asarray(native["entries"], dtype=bool)
    assert len(leg) == len(nat) == len(df)
    assert leg.sum() >= min_entries, (
        f"caso trivial ({leg.sum()} entradas): el test no está midiendo nada"
    )
    assert np.array_equal(leg, nat), (
        f"entries divergen: legacy={leg.sum()} native={nat.sum()} "
        f"primeras diffs={np.flatnonzero(leg != nat)[:10]}"
    )
    lex = np.asarray(legacy["exits"], dtype=bool)
    nex = np.asarray(native["exits"], dtype=bool)
    assert np.array_equal(lex, nex), (
        f"exits divergen: legacy={lex.sum()} native={nex.sum()}"
    )
    return leg


def test_fase2_la_familia_va_por_el_carril_nativo():
    """PRD §7.1, Fase 2: la familia ESTÁ en _RAW_INDICATOR_DISPATCH y una
    estrategia de comparaciones puras ya NO cae al legacy (has_special=False).
    El HCH con price_level_distance SIGUE yendo al legacy: esa condición no
    tiene paridad nativa garantizada y gatea la estrategia entera."""
    for nombre in ("Pico", "Edad del pico", "Volumen del pico"):
        assert nombre in _RAW_INDICATOR_DISPATCH, (
            f"{nombre} no está en el dispatch nativo: la Fase 2 del PRD no está"
        )
        src = {"name": nombre, "swing_dir": "up", "pivot_window": 3,
               "pivot_rank": 1}
        strat = _strategy([_cmp(src, "GREATER_THAN", -1e9)])
        plan = compile_strategy_def(strat)["_indicator_plan"]
        assert not plan["has_special"], f"{nombre} sigue cayendo al legacy"

        # con price_level_distance (las condiciones 3-4 del HCH del §6): legacy
        dist = {"type": "price_level_distance", "source": src,
                "level": dict(src, pivot_rank=3),
                "comparator": "DISTANCE_LT", "value_pct": 1.5, "position": "any"}
        strat_hch = _strategy([_cmp(src, "GREATER_THAN", -1e9), dist])
        assert compile_strategy_def(strat_hch)["_indicator_plan"]["has_special"], (
            "un price_level_distance con Pico debería gatear la estrategia al legacy"
        )


def test_fase2_clave_de_dedup_distingue_la_familia():
    """LA trampa del §7.1: Pico(1), Pico(2), Valle(1) y Pico(win=5) deben ser
    specs distintas con claves distintas. Si comparten clave, el motor les da
    el MISMO array y el HCH sale siempre verdadero — sin error ni log."""
    p = lambda **kw: {"name": "Pico", "swing_dir": "up", "pivot_window": 3,
                      "pivot_rank": 1, **kw}
    strat = _strategy([
        _cmp(p(), "GREATER_THAN", -1e9),
        _cmp(p(pivot_rank=2), "GREATER_THAN", -1e9),
        _cmp(p(swing_dir="down"), "GREATER_THAN", -1e9),
        _cmp(p(pivot_window=5), "GREATER_THAN", -1e9),
    ])
    plan = compile_strategy_def(strat)["_indicator_plan"]
    claves = [s["key"] for s in plan["specs"] if s["name"] == "Pico"]
    assert len(claves) == 4, f"el plan deduplicó configs distintas: {claves}"
    assert len(set(claves)) == 4


@pytest.mark.parametrize("swing_dir,win", [("up", 2), ("down", 2), ("up", 3)])
def test_fase2_paridad_native_legacy_1m(swing_dir, win):
    """Señales idénticas nativo vs legacy con giros conocidos y con random
    walk: Pico(1) contra Pico(2), Edad y Volumen."""
    df = _dia_giros()
    base = {"name": "Pico", "swing_dir": swing_dir, "pivot_window": win}
    strat = _strategy([
        _cmp(dict(base, pivot_rank=1), "LESS_THAN", dict(base, pivot_rank=2)),
        _cmp({**base, "name": "Edad del pico", "pivot_rank": 2},
             "LESS_THAN", 90),
        _cmp({**base, "name": "Volumen del pico", "pivot_rank": 1},
             "GREATER_THAN", 500),
    ])
    _assert_equivalente_native(strat, df)

    # random walk con huecos (más giros, NaNs mezclados)
    df2 = _dia_aleatorio(seed=7)
    strat2 = _strategy([
        _cmp(dict(base, pivot_rank=1), "GREATER_THAN", dict(base, pivot_rank=3)),
        _cmp({**base, "name": "Edad del pico", "pivot_rank": 1},
             "LESS_THAN", 120),
    ])
    _assert_equivalente_native(strat2, df2)


def test_fase2_paridad_native_legacy_multiplier():
    """El HCH del §6 usa targets 'Pico x 0.97': el multiplier se aplica
    post-cómputo en el legacy (compute_indicator) y el nativo debe hacer
    lo mismo con la familia."""
    df = _dia_giros()
    base = {"name": "Pico", "swing_dir": "up", "pivot_window": 2}
    strat = _strategy([
        _cmp(dict(base, pivot_rank=1), "LESS_THAN",
             dict(base, pivot_rank=2, multiplier=0.97)),
    ])
    _assert_equivalente_native(strat, df)


def test_fase2_paridad_native_legacy_tf5m():
    """tf=5m con huecos de minutos: el resample nativo es por reloj y el eje
    absoluto de la familia debe ser el de la PRIMERA barra de cada bucket
    (= timestamp:'first' del legacy), no el borde del bucket."""
    df = _dia_aleatorio(seed=11, n=480)
    base = {"name": "Pico", "swing_dir": "up", "pivot_window": 2}
    strat = dict(_strategy([
        _cmp(dict(base, pivot_rank=1), "GREATER_THAN", dict(base, pivot_rank=2)),
    ]))
    strat["entry_logic"]["timeframe"] = "5m"
    strat["exit_logic"]["timeframe"] = "5m"
    _assert_equivalente_native(strat, df)


def test_fase2_paridad_native_legacy_multidia():
    """Frame de dos días: el reinicio diario tiene que dar igual en ambos
    carriles (el nativo deriva el día del eje absoluto de minutos)."""
    d1 = _dia_giros(date="2024-11-12")
    d2 = _dia_giros(date="2024-11-13", offset=5.0)
    df = pd.concat([d1, d2], ignore_index=True)
    base = {"name": "Pico", "swing_dir": "up", "pivot_window": 2}
    strat = _strategy([
        _cmp(dict(base, pivot_rank=1), "LESS_THAN", dict(base, pivot_rank=2)),
    ])
    entries = _assert_equivalente_native(strat, df)
    # y que el día 2 dispare también (el reinicio no lo deja heredadando NaN)
    assert entries[len(d1):].any(), "el día 2 no generó entradas"


def test_fase2_paridad_native_legacy_cruce_valle():
    """La ENTRADA del HCH (condición 6): Bar Close CRUZA POR DEBAJO del
    valle rank=1. Los cruces replican shift(1) del legacy."""
    df = _dia_aleatorio(seed=13, n=360)
    valle = {"name": "Pico", "swing_dir": "down", "pivot_window": 3,
             "pivot_rank": 1}
    strat = _strategy([
        _cmp({"name": "Close"}, "CROSSES_BELOW", valle),
    ])
    _assert_equivalente_native(strat, df)
