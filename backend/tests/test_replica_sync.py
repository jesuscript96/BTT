"""
EPIC C (PRD rendimiento-backtester) — réplica local de slabs con fuente configurable.

Se testea el branch de fuente LOCAL (mirror con layout hive), que es además el modo
post-migración de datos al hardware propio. El branch GCS comparte todo el código
salvo el listado (glob DuckDB) — cubierto por el contrato de discover_months.
"""
import datetime

import numpy as np
import pandas as pd
import pytest

from app.db import gcs_cache, replica_sync, slab_store
from app.db.slab_builder import slab_paths


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(gcs_cache, "LOCAL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("BTT_SLAB_DIR", str(tmp_path / "slabs"))
    slab_store._OPEN_SLABS.clear()
    yield
    slab_store._OPEN_SLABS.clear()


def _mk_month_frame(ticker, y, m, days=3, n=30, seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    for d in range(1, days + 1):
        date = f"{y}-{m:02d}-{d:02d}"
        ts = pd.date_range(f"{date} 09:30", periods=n, freq="1min")
        close = 10 + rng.normal(0, 0.1, n).cumsum()
        frames.append(pd.DataFrame({
            "ticker": ticker, "date": date, "timestamp": ts,
            "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": rng.integers(100, 999, n),
        }))
    return pd.concat(frames, ignore_index=True)


def _mk_local_mirror(root, months, kind_folder="intraday_1m_optimized"):
    """Crea <root>/<folder>/year=Y/month=M/data.parquet con datos sintéticos."""
    for (y, m) in months:
        d = root / kind_folder / f"year={y}" / f"month={m}"
        d.mkdir(parents=True, exist_ok=True)
        df = pd.concat(
            [_mk_month_frame(f"TK{i}", y, m, seed=i * 7 + m) for i in range(3)],
            ignore_index=True,
        )
        df.to_parquet(d / "data.parquet", index=False)
    return str(root)


def test_parse_years():
    assert replica_sync.parse_years("2021-2023") == {2021, 2022, 2023}
    assert replica_sync.parse_years("2024") == {2024}
    assert replica_sync.parse_years("2021,2023") == {2021, 2023}
    assert replica_sync.parse_years("garbage") == set()


def test_discover_months_local_prefers_opt(tmp_path):
    root = tmp_path / "mirror"
    _mk_local_mirror(root, [(2025, 5)], "intraday_1m_optimized")
    _mk_local_mirror(root, [(2025, 5), (2025, 6)], "intraday_1m")

    months = replica_sync.discover_months(str(root))
    by_key = {(x["year"], x["month"]): x["kind"] for x in months}
    assert by_key == {(2025, 5): "opt", (2025, 6): "raw"}


def test_sync_builds_skips_and_rebuilds_current_month(tmp_path):
    root = _mk_local_mirror(tmp_path / "mirror", [(2025, 5), (2025, 6)])
    fake_today = datetime.date(2025, 6, 15)  # junio = mes corriente

    r1 = replica_sync.run_sync_once(source=root, years={2025}, now=fake_today)
    assert r1 == {"built": 2, "skipped": 0, "failed": 0, "months": 2}
    assert slab_store.slab_exists("opt", 2025, 5)
    assert slab_store.slab_exists("opt", 2025, 6)

    # segunda pasada: mayo al día (skip); junio (corriente) se reconstruye
    r2 = replica_sync.run_sync_once(source=root, years={2025}, now=fake_today)
    assert r2["built"] == 1 and r2["skipped"] == 1 and r2["failed"] == 0

    # el slab construido sirve datos correctos
    slab = slab_store.get_month("opt", 2025, 5)
    assert slab is not None and slab.n_rows == 3 * 3 * 30
    assert slab.slice_pair("TK0", "2025-05-01") is not None


def test_sync_years_filter(tmp_path):
    root = _mk_local_mirror(tmp_path / "mirror", [(2024, 12), (2025, 1)])
    r = replica_sync.run_sync_once(source=root, years={2025}, now=datetime.date(2025, 3, 1))
    assert r["months"] == 1 and r["built"] == 1
    assert not slab_store.slab_exists("opt", 2024, 12)
    assert slab_store.slab_exists("opt", 2025, 1)


def test_sync_never_raises_on_bad_source(tmp_path):
    # fuente inexistente → 0 meses, sin excepción
    r = replica_sync.run_sync_once(source=str(tmp_path / "nope"), years=set(),
                                   now=datetime.date(2025, 1, 1))
    assert r == {"built": 0, "skipped": 0, "failed": 0, "months": 0}

    # parquet corrupto → failed, sin excepción
    root = tmp_path / "mirror"
    d = root / "intraday_1m_optimized" / "year=2025" / "month=2"
    d.mkdir(parents=True)
    (d / "data.parquet").write_bytes(b"not a parquet")
    r2 = replica_sync.run_sync_once(source=str(root), years={2025},
                                    now=datetime.date(2025, 3, 1))
    assert r2["failed"] == 1 and r2["built"] == 0


def test_warm_page_cache_reads_all_slabs(tmp_path):
    root = _mk_local_mirror(tmp_path / "mirror", [(2025, 5)])
    replica_sync.run_sync_once(source=root, years={2025}, now=datetime.date(2025, 7, 1))
    import os
    slab_size = os.path.getsize(slab_paths("opt", 2025, 5)["slab"])
    read = replica_sync.warm_page_cache()
    assert read == slab_size

    # límite respetado
    read_capped = replica_sync.warm_page_cache(max_bytes=100)
    assert 0 < read_capped <= 8 * 1024 * 1024
