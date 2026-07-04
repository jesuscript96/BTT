"""
Regresión (hallazgo del bench a escala): un slab construido desde el caché por-ticker
NO debe servirse si la fuente cambió después — ensure_slabs_from_ticker_cache compara
la huella de la fuente (manifest.source_fingerprint) y reconstruye.
"""
import numpy as np
import pandas as pd
import pytest

from app.db import gcs_cache, slab_store


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(gcs_cache, "LOCAL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("BTT_SLAB_DIR", str(tmp_path / "slabs"))
    slab_store._OPEN_SLABS.clear()
    yield
    slab_store._OPEN_SLABS.clear()


def _write_ticker(tk, close_base, y=2025, m=9, n=30):
    ts = pd.date_range(f"{y}-{m:02d}-01 09:30", periods=n, freq="1min")
    df = pd.DataFrame({
        "ticker": tk, "date": f"{y}-{m:02d}-01", "timestamp": ts,
        "open": close_base, "high": close_base * 1.01, "low": close_base * 0.99,
        "close": close_base, "volume": 100,
    })
    df = gcs_cache._downcast_intraday(df)
    gcs_cache._atomic_write_parquet(df, gcs_cache._ticker_cache_path(y, m, "opt", tk))


def test_stale_slab_rebuilds_on_source_change():
    _write_ticker("AAA", 10.0)
    assert slab_store.ensure_slabs_from_ticker_cache([(2025, 9)]) == 1
    slab = slab_store.get_month("opt", 2025, 9)
    assert float(slab.slice_pair("AAA", "2025-09-01").close[0]) == np.float32(10.0)
    assert slab.lookup("BBB", "2025-09-01") is None

    # la fuente cambia: AAA reescrito con otros precios + ticker NUEVO
    _write_ticker("AAA", 20.0)
    _write_ticker("BBB", 5.0)

    built = slab_store.ensure_slabs_from_ticker_cache([(2025, 9)])
    assert built == 1, "la huella cambió → debe reconstruir"

    slab2 = slab_store.get_month("opt", 2025, 9)
    assert float(slab2.slice_pair("AAA", "2025-09-01").close[0]) == np.float32(20.0)
    assert slab2.lookup("BBB", "2025-09-01") is not None

    # sin cambios → no reconstruye
    assert slab_store.ensure_slabs_from_ticker_cache([(2025, 9)]) == 0
