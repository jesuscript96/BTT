"""
La vía materializada del qualifying (QUALIFYING_WINDOWED_PARQUET) debe calcular
AL VUELO las columnas de ventana que la regla usa y el parquet no trae.

Hallazgo 25-sep·16: el parquet bygap (generado el 7-sep) solo lleva los 12
lag_rth_*/pm_high _1/_2; una regla con lag_day_return_pct_1 (filtro 1.6) — o
cualquier otra fuente de PREV_DAY_LAG_SOURCES añadida después de generar el
parquet — revienta el backtest con "Binder Error: Referenced column … not
found". Fix: data_service pide a qualifying_windows.on_the_fly_window_selects
las expresiones de las columnas que faltan y las inyecta en una subquery antes
del WHERE (misma SQL con la que se genera el parquet → paridad por
construcción).

Estos tests validan SIN lago real (DuckDB in-memory + parquet mini en tmp):
  1. El registro al-vuelo separa lo computable de lo desconocido.
  2. Una regla lag_day_return_pct_1 < 0 por la vía materializada NO falla y
     devuelve exactamente los ticker-días esperados.
  3. PARIDAD: para CADA fuente de PREV_DAY_LAG_SOURCES, el mismo filtro da los
     mismos ticker-días por la vía materializada y por la vía stage-2 (env
     sin poner) sobre los mismos datos.
  4. Una columna que ni el parquet ni el registro pueden producir sigue
     fallando RUIDOSAMENTE (no se filtra en silencio).
"""
import duckdb
import pytest

from app.services import data_service
from app.services.data_service import _fetch_qualifying_data_uncached
from app.services.qualifying_windows import (
    PREV_DAY_LAG_SOURCES,
    on_the_fly_window_selects,
)


# ─── Datos: 2 tickers × 5 días, columnas base para todas las fuentes ────────

def _make_con(ruta_parquet: str) -> duckdb.DuckDBPyConnection:
    """Con in-memory con daily_metrics y un parquet bygap mini SIN los lag
    de PREV_DAY_LAG_SOURCES (como el real del 7-sep: solo lag_rth_close_1)."""
    con = duckdb.connect(":memory:")
    estaticas = ["ticker VARCHAR", '"timestamp" TIMESTAMP', "rth_open DOUBLE",
                 "rth_high DOUBLE", "rth_low DOUBLE", "rth_close DOUBLE",
                 "rth_volume BIGINT", "pm_high DOUBLE", "pm_low DOUBLE",
                 # el select 3.2 (lag_ret5d_pct_1) viaja SIEMPRE en stage-2 y
                 # usa close/prev_close: el mini-lago las necesita aunque ningún
                 # test de este fichero filtre por la ventana
                 '"close" DOUBLE', '"prev_close" DOUBLE',
                 # mecha sup víspera (paquete 28-sep): OHLC diario completo
                 '"high" DOUBLE', '"low" DOUBLE']
    for src in PREV_DAY_LAG_SOURCES:
        if any(c.startswith(f"{src} ") for c in estaticas):
            continue  # rth_close / rth_volume ya están
        tipo = "BIGINT" if src == "rth_volume" else "DOUBLE"
        estaticas.append(f'"{src}" {tipo}')
    con.execute(f'CREATE TABLE daily_metrics ({", ".join(estaticas)})')
    nombres = [c.split()[0].strip('"') for c in estaticas]
    # día a día: patrones distintos por fuente para que el filtro separe
    dias = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"]
    pat = {  # [AAA..., BBB...] por fuente: neg/pos alternados
        "rth_close": ([10.0, 11.0, 12.0, 13.0, 14.0], [20.0, 19.0, 18.0, 17.0, 16.0]),
        "rth_volume": ([1e6, 3e6, 9e6, 2e6, 5e6], [8e6, 4e6, 2e6, 6e6, 1e6]),
        "gap_pct": ([5.0, -2.0, 7.0, -4.0, 6.0], [3.0, 8.0, -6.0, 2.0, -9.0]),
        "pm_volume": ([500e3, 900e3, 200e3, 800e3, 300e3],
                      [700e3, 100e3, 600e3, 400e3, 900e3]),
        "open": ([9.0, 10.5, 11.0, 12.5, 13.0], [21.0, 18.0, 19.5, 16.0, 17.5]),
        "pmh_gap_pct": ([50.0, 20.0, 80.0, 10.0, 60.0],
                        [30.0, 90.0, 40.0, 70.0, 55.0]),
        "rth_range_pct": ([4.0, 9.0, 2.0, 7.0, 3.0], [8.0, 1.0, 6.0, 5.0, 2.5]),
        "day_return_pct": ([2.0, -1.5, 3.0, -2.0, 1.0],
                           [1.0, 0.5, -3.0, 2.0, -0.5]),
    }
    fijos = {"rth_open": 10.0, "rth_high": 12.0, "rth_low": 8.0,
             "pm_high": 13.0, "pm_low": 7.0, "close": 10.0, "prev_close": 10.0,
             "high": 11.0, "low": 9.0}
    for i, d in enumerate(dias):
        for t, j in (("AAA", 0), ("BBB", 1)):
            fila = {"ticker": t, "timestamp": d, **fijos}
            for src in PREV_DAY_LAG_SOURCES:
                fila[src] = pat[src][j][i]
            con.execute(
                f'INSERT INTO daily_metrics ({", ".join(chr(34)+n+chr(34) for n in nombres)}) '
                f'VALUES ({", ".join("?" for _ in nombres)})',
                [fila[n] for n in nombres],
            )
    # parquet "bygap" mini: mismas filas + SOLO lag_rth_close_1 (como el real:
    # trae los 12 lag_rth_*/pm_high; aquí basta uno para simular el caso)
    con.execute(f"""
        COPY (
            SELECT *, LAG(rth_close, 1) OVER (
                PARTITION BY ticker ORDER BY "timestamp") AS lag_rth_close_1
            FROM daily_metrics
        ) TO '{ruta_parquet}' (FORMAT PARQUET)
    """)
    return con


def _filtros(metrica, op="<", valor="0"):
    return {
        "start_date": "2024-01-01", "end_date": "2024-12-31",
        "rules": [{"metric": metrica, "operator": op,
                   "valueType": "static", "value": valor}],
    }


def _td(df):
    return sorted(zip(df["ticker"], df["date"]))


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    ruta = str(tmp_path / "bygap_mini.parquet")
    con = _make_con(ruta)
    monkeypatch.setenv("DB_PROVIDER", "local")
    monkeypatch.setenv("QUALIFYING_WINDOWED_PARQUET", ruta)
    monkeypatch.setattr("app.database.get_db_connection", lambda: con)
    yield ruta, con, monkeypatch
    con.close()


def test_registro_al_vuelo_separa_conocidas_y_desconocidas():
    sel, desc = on_the_fly_window_selects(
        {"lag_day_return_pct_1", "lead_open_2", "lag_inexistente_9"})
    alias = [s.split(" AS ")[-1] for s in sel]
    assert "lag_day_return_pct_1" in alias and "lead_open_2" in alias
    assert desc == ["lag_inexistente_9"]


def test_materializada_con_lag_faltante_no_falla(entorno):
    # antes del fix: Binder Error "Referenced column lag_day_return_pct_1 not found"
    df = _fetch_qualifying_data_uncached(
        "dataset-test", filtros=_filtros("lag_day_return_pct_1"))
    # day_return_pct AAA [2,-1.5,3,-2,1] -> lag<0 en d3 y d5
    # BBB [1,0.5,-3,2,-0.5] -> lag<0 en d4
    assert _td(df) == [("AAA", "2024-01-04"), ("AAA", "2024-01-06"),
                       ("BBB", "2024-01-05")]


@pytest.mark.parametrize("src", PREV_DAY_LAG_SOURCES)
def test_paridad_materializada_vs_stage2(entorno, src):
    metrica = f"lag_{src}_1"
    df_mat = _fetch_qualifying_data_uncached("dataset-test", filtros=_filtros(metrica))
    entorno[2].delenv("QUALIFYING_WINDOWED_PARQUET")
    df_s2 = _fetch_qualifying_data_uncached("dataset-test", filtros=_filtros(metrica))
    assert _td(df_mat) == _td(df_s2), f"{metrica}: materializada != stage-2"
    # y los valores de la propia columna también (no solo el recuento)
    m = df_mat.set_index(["ticker", "date"])[metrica].to_dict()
    s = df_s2.set_index(["ticker", "date"])[metrica].to_dict()
    for k in m:
        assert m[k] == s[k]


def test_columna_desconocida_siguen_fallando_ruidosamente(entorno):
    with pytest.raises(Exception) as ei:
        _fetch_qualifying_data_uncached(
            "dataset-test", filtros=_filtros("lag_inventada_del_future_1"))
    assert "lag_inventada_del_future_1" in str(ei.value)


# ─── Filtro 3.2 (lag_ret5d_pct_1): ventana compuesta, no LAG de una columna ──

def test_registro_conoce_la_ventana_ret5d():
    sel, desc = on_the_fly_window_selects({"lag_ret5d_pct_1"})
    assert [s.split(" AS ")[-1] for s in sel] == ["lag_ret5d_pct_1"]
    assert desc == []


@pytest.fixture()
def entorno_ret5d(tmp_path, monkeypatch):
    """Mini-lago 1 ticker × 7 días con r = −0,1 por sesión (AAA) + BBB de 2
    días (ventana SIEMPRE NULL) y parquet bygap SIN lag_ret5d_pct_1 (como el
    real del 7-sep: la ventana no existe allí)."""
    ruta = str(tmp_path / "bygap_ret5d.parquet")
    con = duckdb.connect(":memory:")
    # columnas base completas: la vía stage-2 selecciona todo su repertorio
    con.execute(
        'CREATE TABLE daily_metrics (ticker VARCHAR, "timestamp" TIMESTAMP, '
        '"close" DOUBLE, "prev_close" DOUBLE, rth_open DOUBLE, rth_high DOUBLE, '
        "rth_low DOUBLE, rth_close DOUBLE, rth_volume BIGINT, pm_high DOUBLE, "
        "pm_low DOUBLE, gap_pct DOUBLE, pm_volume BIGINT, \"open\" DOUBLE, "
        "pmh_gap_pct DOUBLE, rth_range_pct DOUBLE, day_return_pct DOUBLE, "
        # mecha sup víspera (paquete 28-sep): OHLC diario completo
        '"high" DOUBLE, "low" DOUBLE)'
    )
    for i in range(7):
        con.execute(
            'INSERT INTO daily_metrics VALUES (?, ?, ?, ?, 10.0, 12.0, 8.0, 10.0, '
            "1000000, 13.0, 7.0, 5.0, 500000, 10.0, 50.0, 3.0, 1.0, 11.0, 9.0)",
            ["AAA", f"2024-01-{i + 1:02d}", 10.0 * 0.9 ** i,
             10.0 * 0.9 ** (i - 1) if i else 10.0],
        )
    for i in range(2):
        con.execute(
            'INSERT INTO daily_metrics VALUES (?, ?, ?, ?, 10.0, 12.0, 8.0, 10.0, '
            "1000000, 13.0, 7.0, 5.0, 500000, 10.0, 50.0, 3.0, 1.0, 11.0, 9.0)",
            ["BBB", f"2024-01-{i + 1:02d}", 10.0, 10.0],
        )
    con.execute(
        f"COPY (SELECT * FROM daily_metrics) TO '{ruta}' (FORMAT PARQUET)"
    )
    monkeypatch.setenv("DB_PROVIDER", "local")
    monkeypatch.setenv("QUALIFYING_WINDOWED_PARQUET", ruta)
    monkeypatch.setattr("app.database.get_db_connection", lambda: con)
    yield ruta, con, monkeypatch
    con.close()


def test_materializada_ret5d_no_falla_y_paridad_con_stage2(entorno_ret5d):
    # antes de la ventana: Binder Error "Referenced column lag_ret5d_pct_1 not found"
    df_mat = _fetch_qualifying_data_uncached(
        "dataset-test", filtros=_filtros("lag_ret5d_pct_1"))
    # la ventana de 5 sesiones está completa desde el 6-ene. La del 6-ene
    # incluye el día 0 (r = 0: close = prev_close = 10, válido pero plano) →
    # producto 0,9⁴; la del 7-ene son los cinco r = −0,1 → 0,9⁵.
    assert _td(df_mat) == [("AAA", "2024-01-06"), ("AAA", "2024-01-07")]
    valores = df_mat.set_index("date")["lag_ret5d_pct_1"].to_dict()
    assert valores["2024-01-06"] == pytest.approx(100 * (0.9 ** 4 - 1))
    assert valores["2024-01-07"] == pytest.approx(100 * (0.9 ** 5 - 1))

    entorno_ret5d[2].delenv("QUALIFYING_WINDOWED_PARQUET")
    df_s2 = _fetch_qualifying_data_uncached(
        "dataset-test", filtros=_filtros("lag_ret5d_pct_1"))
    assert _td(df_s2) == _td(df_mat)
    m = df_mat.set_index(["ticker", "date"])["lag_ret5d_pct_1"].to_dict()
    s = df_s2.set_index(["ticker", "date"])["lag_ret5d_pct_1"].to_dict()
    for k in m:
        assert m[k] == pytest.approx(s[k])


def test_missing_include_en_materializada_y_stage2(entorno_ret5d):
    """"Si falta el dato: incluir" — los NULL (BBB sin historial y los primeros
    días de AAA) pasan la regla, en la vía materializada Y en stage-2."""
    filtros_inc = {
        "start_date": "2024-01-01", "end_date": "2024-12-31",
        "rules": [{"metric": "lag_ret5d_pct_1", "operator": "LESS_THAN",
                   "valueType": "static", "value": "0", "missing": "include"}],
    }
    df_mat = _fetch_qualifying_data_uncached("dataset-test", filtros=filtros_inc)
    # por valor: AAA 6/7-ene (−34,4 / −41,0 %); por NULL: AAA 1-5-ene (ventanas
    # incompletas) y BBB 1/2-ene (sin historial)
    assert _td(df_mat) == sorted(
        [("AAA", f"2024-01-0{d}") for d in range(1, 8)]
        + [("BBB", "2024-01-01"), ("BBB", "2024-01-02")]
    )
    entorno_ret5d[2].delenv("QUALIFYING_WINDOWED_PARQUET")
    df_s2 = _fetch_qualifying_data_uncached("dataset-test", filtros=filtros_inc)
    assert _td(df_s2) == _td(df_mat)


def test_materializada_days_since_first_day_y_paridad(entorno_ret5d):
    """6.1: la vía materializada computa days_since_first_day al vuelo (el
    parquet bygap no lo trae) y coincide con stage-2 (AAA nace el 1-ene)."""
    filtros_61 = {
        "start_date": "2024-01-01", "end_date": "2024-12-31",
        "rules": [{"metric": "days_since_first_day", "operator": "LESS_THAN",
                   "valueType": "static", "value": "5"}],
    }
    df_mat = _fetch_qualifying_data_uncached("dataset-test", filtros=filtros_61)
    # AAA: 1-ene = dia 0 .. 7-ene = dia 6 -> <5 son 1..5-ene (dias 0..4);
    # BBB (nace 1-ene, 2 dias): 1..2-ene
    assert _td(df_mat) == sorted(
        [("AAA", f"2024-01-0{d}") for d in range(1, 6)]
        + [("BBB", "2024-01-01"), ("BBB", "2024-01-02")]
    )
    entorno_ret5d[2].delenv("QUALIFYING_WINDOWED_PARQUET")
    df_s2 = _fetch_qualifying_data_uncached("dataset-test", filtros=filtros_61)
    assert _td(df_s2) == _td(df_mat)
    m = df_mat.set_index(["ticker", "date"])["days_since_first_day"].to_dict()
    s = df_s2.set_index(["ticker", "date"])["days_since_first_day"].to_dict()
    for k in m:
        assert m[k] == s[k]
