"""
Paridad de la vía rápida de qualifying (bygap) vs la vía original — FIX C del
PRD_ADOPCION_QUALIFYING_BYGAP_ALVARO.md (§2).

Compara celda a celda (por VALORES, no solo recuentos) la selección de
candidatos con y sin `QUALIFYING_WINDOWED_PARQUET`, en los tres `apply_day`
(gap_day / gap_1_day / gap_2_day), con otro umbral de gap (>=20) y en el borde
derecho del dataset (2026-07-14 → 2026-08-14 con gap_1_day: filas cuyos
`lead_*` son NULL — el caso que más preocupaba a Sailor; el
`dropna(subset=['lead_timestamp_1'])` debe caer en las mismas filas en ambas
vías, lo que `assert_frame_equal` sobre el frame completo cubre).

Llama directamente a `_fetch_qualifying_data_uncached` (la capa Redis/disco de
`fetch_qualifying_data` no participa: no hay que neutralizarla, y es la
función donde vive la vía rápida).

Tolerancia rtol/atol=1e-9 ESTRICTA: si hubiera que aflojarla para que pase, es
señal de bug (el bygap materializa los mismos doubles), no de tolerancia
demasiado dura.

Requisitos para que corra de verdad (si falta algo, SALTA con motivo):
  - `QUALIFYING_WINDOWED_PARQUET` configurada (backend/.env) como GLOB
    (`.../daily_metrics_bygap/*.parquet`, FIX B) con al menos un fichero
    (bygap generado con opt_por_gap.py).
  - Ejecutar desde `backend/` y con el backend PARADO: la vía original abre
    `local_data.duckdb` en escritura y DuckDB no admite dos escritores.
"""
import glob
import inspect
import os

import pandas as pd
import pytest

from app.services import data_service
from app.services.data_service import _fetch_qualifying_data_uncached

# Dataset real con reglas (PMH Gap % >= 50 y Min Open PM price > 1): fuerza la
# rama SQL `provider == "local" and (has_custom_rules or not use_hot_cache)`,
# la única que la vía rápida sustituye.
DATASET_ID = "8bb15d22-5065-468d-9aeb-18165596cc47"

CASES = [
    ("2020-01-01", "2026-08-14", "gap_day"),
    ("2022-01-01", "2023-12-31", "gap_day"),
    ("2021-01-01", "2026-08-14", "gap_day"),     # umbral distinto en el dataset
    ("2022-01-01", "2023-12-31", "gap_1_day"),
    ("2022-01-01", "2023-12-31", "gap_2_day"),
    # Borde derecho: últimas velas de cada ticker, lead_* NULL (2026-08-14 es
    # el último día de datos) — el dropna de lead_timestamp_1 debe caer igual.
    ("2026-07-14", "2026-08-14", "gap_1_day"),
]


@pytest.fixture()
def dataset_id():
    return DATASET_ID


def _run(dsid, s, e, ad):
    return (_fetch_qualifying_data_uncached(dsid, req_start_date=s, req_end_date=e, apply_day=ad)
            .sort_values(["ticker", "date"], kind="stable")
            .reset_index(drop=True))


def _require_fast_path() -> None:
    """Salta (no falla) si la vía rápida no está operativa en este entorno."""
    if "QUALIFYING_WINDOWED_PARQUET" not in inspect.getsource(
        data_service._fetch_qualifying_data_uncached
    ):
        pytest.skip("vía rápida no presente en data_service")
    win = os.environ.get("QUALIFYING_WINDOWED_PARQUET", "").strip()
    if not win:
        pytest.skip("QUALIFYING_WINDOWED_PARQUET sin configurar (backend/.env)")
    if not glob.glob(win):
        pytest.skip(f"bygap no generado: el glob no resuelve a ningún fichero ({win})")


def _assert_parity(base: pd.DataFrame, fast: pd.DataFrame) -> None:
    assert len(base) == len(fast)
    # Guard extra: una columna que falte en el bygap no puede esconderse en la
    # intersección de columnas del assert_frame_equal.
    assert set(base.columns) == set(fast.columns), (
        f"columnas distintas: solo-base={set(base.columns) - set(fast.columns)} "
        f"solo-fast={set(fast.columns) - set(base.columns)}"
    )
    cols = [c for c in base.columns if c in fast.columns]
    pd.testing.assert_frame_equal(base[cols], fast[cols],
                                  check_like=True, check_dtype=False,
                                  rtol=1e-9, atol=1e-9)


@pytest.mark.parametrize("s,e,ad", CASES)
def test_parity(monkeypatch, dataset_id, s, e, ad):
    _require_fast_path()
    win = os.environ["QUALIFYING_WINDOWED_PARQUET"].strip()
    monkeypatch.delenv("QUALIFYING_WINDOWED_PARQUET", raising=False)
    base = _run(dataset_id, s, e, ad)
    monkeypatch.setenv("QUALIFYING_WINDOWED_PARQUET", win)
    fast = _run(dataset_id, s, e, ad)
    _assert_parity(base, fast)


def test_parity_umbral_gap_20(monkeypatch):
    """Umbral de gap distinto (PMH Gap % >= 20): filtra solo por la columna de
    orden del bygap. Los filtros se inyectan parcheando _resolve_filters para
    no escribir datasets de prueba en users.duckdb."""
    _require_fast_path()
    win = os.environ["QUALIFYING_WINDOWED_PARQUET"].strip()

    def _fake_resolve(dataset_id, req_start, req_end):
        return {
            "start_date": req_start,
            "end_date": req_end,
            "rules": [
                {"field": "PMH Gap %", "operator": "GREATER_THAN_OR_EQUAL", "value": 20},
            ],
        }

    monkeypatch.setattr(data_service, "_resolve_filters", _fake_resolve)
    monkeypatch.delenv("QUALIFYING_WINDOWED_PARQUET", raising=False)
    base = _run("umbral-20", "2022-01-01", "2023-12-31", "gap_day")
    monkeypatch.setenv("QUALIFYING_WINDOWED_PARQUET", win)
    fast = _run("umbral-20", "2022-01-01", "2023-12-31", "gap_day")
    _assert_parity(base, fast)
