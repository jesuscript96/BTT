"""
Filtro «Hora de inicio del gap» (5.2-bis, ORDEN §3 de Álvaro): t del primer
cruce de +X % en la línea continua 16:00 víspera → 09:30, como regla de
dataset con umbral movible sobre el pivote gap_start.parquet (LEFT JOIN).

Sin lago real (DuckDB in-memory + parquets mini):
  1. Vía stage-2 (local): la regla selecciona EXACTO los ticker-días
     esperados; sin-dato (NULL = no cruzó) pasa con missing=include.
  2. PARIDAD materializada (al-vuelo, bygap mini) vs stage-2 con el join.
  3. El guard del hot-cache excluye reglas gap_start_*.
  4. El detector needs_gap_start no dispara con otras columnas.
"""
import duckdb
import pytest

from app.services.data_service import _can_use_hot_cache, _fetch_qualifying_data_uncached
from app.services.qualifying_windows import needs_gap_start

DIAS = ["2024-01-02", "2024-01-03", "2024-01-04"]

# Cruces (t desde las 16:00): AAA 700 (= 03:40 madrugada) · BBB 820 (= 05:40)
# · CCC NULL (no cruzó el 50 ese día).
CRUCES = {
    "AAA": [700, 701, 702],
    "BBB": [820, None, 819],
    "CCC": [None, None, None],
}


def _make_con(ruta_bygap: str, ruta_gap_start: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("""
        CREATE TABLE daily_metrics (
            ticker VARCHAR, "timestamp" TIMESTAMP, rth_open DOUBLE,
            rth_high DOUBLE, rth_low DOUBLE, rth_close DOUBLE, rth_volume BIGINT,
            pm_high DOUBLE, pm_low DOUBLE, "open" DOUBLE, "high" DOUBLE,
            "low" DOUBLE, "close" DOUBLE, prev_close DOUBLE,
            pmh_gap_pct DOUBLE, gap_pct DOUBLE, day_return_pct DOUBLE,
            pm_volume BIGINT, rth_range_pct DOUBLE
        )
    """)
    vals = []
    for tk in ("AAA", "BBB", "CCC"):
        for d in DIAS:
            vals.append(
                f"('{tk}', TIMESTAMP '{d} 00:00:00', 10, 12, 8, 10, 1000000, 13, 7, "
                f"10, 11, 9, 10, 10, 60, 5, 0, 500000, 3)"
            )
    con.execute(f"INSERT INTO daily_metrics VALUES {', '.join(vals)}")
    con.execute(f"""
        COPY (SELECT * FROM daily_metrics) TO '{ruta_bygap}' (FORMAT PARQUET)
    """)
    # pivote gap_start mini: (ticker, fecha, gap_start_min_50)
    filas = []
    for tk, ts in CRUCES.items():
        for d, t in zip(DIAS, ts):
            filas.append((tk, d, t))
    con.execute("CREATE TABLE gs (ticker VARCHAR, fecha VARCHAR, gap_start_min_50 DOUBLE)")
    con.execute("INSERT INTO gs VALUES " + ", ".join(
        f"('{t}', '{d}', {v if v is not None else 'NULL'})" for t, d, v in filas))
    con.execute(f"COPY (SELECT * FROM gs) TO '{ruta_gap_start}' (FORMAT PARQUET)")
    return con


def _filtros(metrica, op, valor, missing=None):
    r = {"metric": metrica, "operator": op, "valueType": "static", "value": str(valor)}
    if missing:
        r["missing"] = missing
    return {
        "start_date": "2024-01-01", "end_date": "2024-12-31",
        "rules": [r],
    }


def _td(df):
    return sorted(zip(df["ticker"], df["date"]))


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    ruta_bygap = str(tmp_path / "bygap_mini.parquet")
    ruta_gs = str(tmp_path / "gap_start_mini.parquet").replace("\\", "/")
    con = _make_con(ruta_bygap, ruta_gs)
    monkeypatch.setenv("DB_PROVIDER", "local")
    monkeypatch.setenv("QUALIFYING_WINDOWED_PARQUET", ruta_bygap)
    monkeypatch.setenv("GAP_START_TABLE", ruta_gs)
    monkeypatch.setattr("app.database.get_db_connection", lambda: con)
    yield con, monkeypatch
    con.close()


def test_stage2_seleccion_exacta(entorno):
    # ≤ 780 (antes de las 05:00): AAA los 3 días (700-702); BBB nunca (820,
    # NULL, 819: todos > 780); CCC NULL fuera (sin missing)
    df = _fetch_qualifying_data_uncached(
        "dataset-test", filtros=_filtros("gap_start_min_50", "LESS_THAN_OR_EQUAL", 780))
    assert _td(df) == [("AAA", "2024-01-02"), ("AAA", "2024-01-03"),
                       ("AAA", "2024-01-04")]


def test_sin_dato_incluye(entorno):
    # sin missing: CCC (NULL) queda fuera; con include pasa
    df_sin = _fetch_qualifying_data_uncached(
        "dataset-test", filtros=_filtros("gap_start_min_50", "LESS_THAN_OR_EQUAL", 700))
    assert _td(df_sin) == [("AAA", "2024-01-02")]
    df_con = _fetch_qualifying_data_uncached(
        "dataset-test", filtros=_filtros("gap_start_min_50", "LESS_THAN_OR_EQUAL", 700, missing="include"))
    # NULL (sin cruce): CCC los 3 días y BBB el 03
    assert _td(df_con) == [("AAA", "2024-01-02"), ("BBB", "2024-01-03"),
                           ("CCC", "2024-01-02"), ("CCC", "2024-01-03"),
                           ("CCC", "2024-01-04")]


def test_paridad_materializada_vs_stage2(entorno):
    con, mp = entorno
    df_mat = _fetch_qualifying_data_uncached(
        "dataset-test", filtros=_filtros("gap_start_min_50", "LESS_THAN_OR_EQUAL", 780))
    mp.delenv("QUALIFYING_WINDOWED_PARQUET")
    df_s2 = _fetch_qualifying_data_uncached(
        "dataset-test", filtros=_filtros("gap_start_min_50", "LESS_THAN_OR_EQUAL", 780))
    assert _td(df_mat) == _td(df_s2)
    m = df_mat.set_index(["ticker", "date"])["gap_start_min_50"].to_dict()
    s2 = df_s2.set_index(["ticker", "date"])["gap_start_min_50"].to_dict()
    for k in m:
        assert m[k] == s2[k]


def test_hot_cache_excluye_gap_start():
    f = {"rules": [{"metric": "gap_start_min_50", "operator": "LESS_THAN",
                    "valueType": "static", "value": "780"}]}
    assert _can_use_hot_cache(f) is False
    # comportamiento preexistente: sin reglas de gap alto NO hay hot cache
    # (la función solo lo permite con Open Gap >= 5 / PMH >= 20)
    assert _can_use_hot_cache({"rules": []}) is False


def test_needs_gap_start_no_dispara_con_otras():
    assert needs_gap_start("pmh_gap_pct >= 50") is False
    assert needs_gap_start("lag_volusd_1 >= 2 AND gap_start_min_20 <= 780") is True
