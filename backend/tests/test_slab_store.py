"""
EPIC B (PRD rendimiento-backtester §03.5-03.6) — unidad del slab store.

Cubre: builder (orden/dedup/índice/manifest/atomicidad), MonthSlab (mmap, zero-copy,
upcast), lookup y casos degenerados (dups, desorden, pares cortos, ticker ausente).
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from app.db import gcs_cache
from app.db import slab_builder, slab_store


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    """Caché por-ticker y slabs en dirs temporales; limpia el caché de slabs abiertos."""
    cache_dir = tmp_path / "cache"
    slab_dir = tmp_path / "slabs"
    cache_dir.mkdir()
    monkeypatch.setattr(gcs_cache, "LOCAL_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BTT_SLAB_DIR", str(slab_dir))
    slab_store._OPEN_SLABS.clear()
    yield
    slab_store._OPEN_SLABS.clear()


def _mk_day(ticker, date, n=60, start_hour=9, start_min=30, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(f"{date} {start_hour:02d}:{start_min:02d}", periods=n, freq="1min")
    close = 10 + rng.normal(0, 0.1, n).cumsum()
    return pd.DataFrame({
        "ticker": ticker, "date": date, "timestamp": ts,
        "open": close * 1.001, "high": close * 1.004,
        "low": close * 0.996, "close": close,
        "volume": rng.integers(100, 9999, n),
    })


def _write_ticker_cache(dfs_by_ticker, y=2025, m=9, kind="opt"):
    for tk, df in dfs_by_ticker.items():
        df = gcs_cache._downcast_intraday(df.copy())
        gcs_cache._atomic_write_parquet(df, gcs_cache._ticker_cache_path(y, m, kind, tk))


def _source_month():
    """Mes sintético con todos los casos degenerados del contrato."""
    a1 = _mk_day("AAA", "2025-09-01", seed=1)
    a2 = _mk_day("AAA", "2025-09-02", seed=2)
    # BBB día 1: timestamps DUPLICADOS con valores distintos (keep-first debe elegir
    # la primera aparición en orden fuente)
    b1 = _mk_day("BBB", "2025-09-01", seed=3)
    dup = b1.iloc[5:8].copy()
    dup["close"] = 999.0  # el duplicado que debe DESCARTARSE
    b1 = pd.concat([b1, dup], ignore_index=True)
    # BBB día 2: filas en DESORDEN
    b2 = _mk_day("BBB", "2025-09-02", seed=4)
    b2 = b2.iloc[::-1].reset_index(drop=True)
    # CCC: solo 3 filas un día (par corto, <5) y un día normal
    c1 = _mk_day("CCC", "2025-09-01", n=3, seed=5)
    c2 = _mk_day("CCC", "2025-09-03", seed=6)
    return {
        "AAA": pd.concat([a1, a2], ignore_index=True),
        "BBB": pd.concat([b1, b2], ignore_index=True),
        "CCC": pd.concat([c1, c2], ignore_index=True),
    }


def test_builder_sorts_dedups_and_indexes():
    src = _source_month()
    _write_ticker_cache(src)
    manifest = slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    assert manifest is not None
    assert manifest["schema_version"] == slab_builder.SCHEMA_VERSION

    slab = slab_store.get_month("opt", 2025, 9)
    assert slab is not None

    idx = slab.pairs()
    # rangos contiguos, sin solapes, cubren todo el slab
    assert idx["row_start"].iloc[0] == 0
    assert (idx["row_end"].values[:-1] == idx["row_start"].values[1:]).all()
    assert idx["row_end"].iloc[-1] == slab.n_rows
    assert (idx["n_rows"] == (idx["row_end"] - idx["row_start"])).all()

    # dedup keep-first: el duplicado con close=999 NO sobrevive
    arrs = slab.slice_pair("BBB", "2025-09-01")
    assert len(arrs) == 60  # 60 originales, 3 dups eliminados
    assert not np.any(arrs.close == np.float32(999.0))

    # desorden corregido: ts estrictamente creciente en cada par
    for tk, d in [("AAA", "2025-09-01"), ("BBB", "2025-09-02"), ("CCC", "2025-09-03")]:
        a = slab.slice_pair(tk, d)
        assert np.all(np.diff(a.ts_ns) > 0), f"{tk} {d} no está ordenado/dedup"

    # el par corto EXISTE en el slab (el filtro <5 es del iterador, no del builder)
    assert slab.lookup("CCC", "2025-09-01") is not None
    # par inexistente
    assert slab.lookup("ZZZ", "2025-09-01") is None
    assert slab.slice_pair("AAA", "2025-09-15") is None


def test_slice_dtypes_and_values_roundtrip():
    src = _source_month()
    _write_ticker_cache(src)
    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    slab = slab_store.get_month("opt", 2025, 9)

    arrs = slab.slice_pair("AAA", "2025-09-02")
    assert arrs.open.dtype == np.float64 and arrs.volume.dtype == np.float64
    assert arrs.ts_ns.dtype == np.int64

    # los valores coinciden con la fuente tras el MISMO downcast float32 del caché
    ref = gcs_cache._downcast_intraday(src["AAA"].copy())
    ref = ref[ref["date"] == "2025-09-02"]
    np.testing.assert_array_equal(arrs.close, ref["close"].values.astype(np.float64))
    np.testing.assert_array_equal(
        arrs.ts_ns, pd.to_datetime(ref["timestamp"]).values.astype(np.int64))

    # ts es vista sin copia sobre el buffer del slab (zero-copy)
    full_rng = slab.lookup("AAA", "2025-09-02")
    assert np.shares_memory(arrs.ts_ns, slab._ts[full_rng[0]:full_rng[1]])
    # la vista datetime64 tampoco copia
    assert np.shares_memory(arrs.timestamps_dt64(), arrs.ts_ns)


def test_manifest_publishes_last_and_get_month_requires_it():
    src = _source_month()
    _write_ticker_cache(src)
    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    paths = slab_builder.slab_paths("opt", 2025, 9)
    with open(paths["manifest"]) as f:
        man = json.load(f)
    assert man["n_pairs"] == 6 and man["n_rows"] > 0

    # sin manifest → slab inválido → get_month None (validez = presencia del trío)
    os.remove(paths["manifest"])
    slab_store._OPEN_SLABS.clear()
    assert slab_store.get_month("opt", 2025, 9) is None


def test_empty_source_returns_none():
    assert slab_builder.build_month_from_ticker_cache(2025, 9, "opt") is None
    assert slab_builder.build_month_from_df(pd.DataFrame(), "opt", 2025, 9) is None


def _qualifying_for(pairs):
    return pd.DataFrame([
        {"ticker": t, "date": d, "prev_close": 10.0, "gap_pct": 50.0} for t, d in pairs
    ])


def test_iter_slab_groups_order_and_filters():
    src = _source_month()
    _write_ticker_cache(src)
    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")

    pairs = [("AAA", "2025-09-01"), ("AAA", "2025-09-02"), ("BBB", "2025-09-01"),
             ("BBB", "2025-09-02"), ("CCC", "2025-09-01"), ("CCC", "2025-09-03"),
             ("ZZZ", "2025-09-01")]  # ZZZ: sin datos → no se emite
    qual = _qualifying_for(pairs)
    qlk = {(r["ticker"], r["date"]): r for r in qual.to_dict("records")}

    out = list(slab_store.iter_slab_groups(qual, [(2025, 9)], {}, qlk))
    keys = [(d, t) for d, t, _, _ in out]
    # orden (date, ticker) lexicográfico; CCC 09-01 fuera (<5 filas); ZZZ fuera (sin datos)
    assert keys == [("2025-09-01", "AAA"), ("2025-09-01", "BBB"),
                    ("2025-09-02", "AAA"), ("2025-09-02", "BBB"),
                    ("2025-09-03", "CCC")]
    # daily_stats es la fila de qualifying
    assert out[0][2]["gap_pct"] == 50.0


def test_iter_slab_groups_exclusions():
    src = _source_month()
    _write_ticker_cache(src)
    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    qual = _qualifying_for([("AAA", "2025-09-01"), ("AAA", "2025-09-02")])
    qlk = {(r["ticker"], r["date"]): r for r in qual.to_dict("records")}

    # 2025-09-01 es lunes (weekday 0): excluir lunes deja solo el 09-02
    strat = {"risk_management": {"exclude_days_active": True, "exclude_days": [0],
                                 "exclude_months": []}}
    out = list(slab_store.iter_slab_groups(qual, [(2025, 9)], strat, qlk))
    assert [(d, t) for d, t, _, _ in out] == [("2025-09-02", "AAA")]

    # excluir septiembre (mes index 8) lo vacía todo
    strat2 = {"risk_management": {"exclude_days_active": True, "exclude_days": [],
                                  "exclude_months": [8]}}
    assert list(slab_store.iter_slab_groups(qual, [(2025, 9)], strat2, qlk)) == []


def test_iter_slab_groups_swing_concat_cross_month():
    """Swing: el día lead sale del slab (incluso de OTRO mes) y se concatena+dedup."""
    _write_ticker_cache({"AAA": _mk_day("AAA", "2025-09-30", seed=7)}, y=2025, m=9)
    _write_ticker_cache({"AAA": _mk_day("AAA", "2025-10-01", seed=8)}, y=2025, m=10)
    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    slab_builder.build_month_from_ticker_cache(2025, 10, "opt")

    qual = pd.DataFrame([{
        "ticker": "AAA", "date": "2025-09-30", "prev_close": 10.0, "gap_pct": 50.0,
        "lead_timestamp_1": pd.Timestamp("2025-10-01"),
    }])
    qlk = {("AAA", "2025-09-30"): qual.iloc[0].to_dict()}
    strat = {"apply_day": "gap_day",
             "risk_management": {"swing_option": {"active": True, "target_day": "gap_1_day"}}}

    out = list(slab_store.iter_slab_groups(qual, [(2025, 9)], strat, qlk))
    assert len(out) == 1
    _, _, _, arrs = out[0]
    assert len(arrs) == 120  # 60 del gap day + 60 del día siguiente
    assert np.all(np.diff(arrs.ts_ns) > 0)

    # lead ausente en slabs (mes sin slab) → no concat, solo el día base
    qual2 = qual.copy()
    qual2.loc[0, "lead_timestamp_1"] = pd.Timestamp("2025-11-03")
    qlk2 = {("AAA", "2025-09-30"): qual2.iloc[0].to_dict()}
    out2 = list(slab_store.iter_slab_groups(qual2, [(2025, 9)], strat, qlk2))
    assert len(out2) == 1 and len(out2[0][3]) == 60
