# -*- coding: utf-8 -*-
"""Los tres filtros de volumen relativo del buscador (22-sep-2026).

«Volume vs 20d avg» y compañía no son columnas de `daily_metrics`: son
cocientes contra la media de los 20 días ANTERIORES del mismo ticker, que el
backend calcula con una ventana de SQL. Aquí se comprueba esa ventana sobre
una base de juguete, porque es donde están las dos trampas:

1. El día actual NO puede entrar en su propia media (`1 PRECEDING`), o el
   cociente se aplana solo.
2. La ventana se calcula sobre la tabla ENTERA y se filtra DESPUÉS. Si se
   calculara después del filtro de fechas, los primeros días del rango se
   quedarían sin sus 20 días previos y el cociente saldría mal sin avisar —
   el patrón de «dos filtros en pasadas distintas» que ya mordió aquí.
"""
import re
from pathlib import Path

import duckdb
import pytest

RAIZ = Path(__file__).resolve().parents[1]
DATA_PY = RAIZ / "app" / "routers" / "data.py"


def _cte_cruda() -> str:
    """La CTE tal cual está escrita en el router: si cambia allí, cambia aquí."""
    texto = DATA_PY.read_text(encoding="utf-8")
    m = re.search(r'query = """\s*(WITH base AS.*?SELECT \* FROM base2 WHERE 1=1)"""',
                  texto, re.S)
    assert m, "no encuentro la CTE en data.py (¿se reescribió la consulta?)"
    return m.group(1)


def _cte() -> str:
    """Con la tabla de circulación vacía: para los tests que solo miran las
    ventanas de volumen."""
    return _cte_con_circ(None)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE daily_metrics (ticker VARCHAR, timestamp TIMESTAMP, "
              "rth_volume DOUBLE, pm_volume DOUBLE)")
    return c


def _mete(c, ticker, volumenes, pm=None):
    for i, v in enumerate(volumenes):
        p = (pm[i] if pm else v / 10)
        c.execute("INSERT INTO daily_metrics VALUES (?, ?, ?, ?)",
                  [ticker, f"2025-01-{i + 1:02d} 00:00:00", float(v), float(p)])


def test_el_dia_normal_da_uno(con):
    _mete(con, "AAA", [1000.0] * 30)
    d = con.execute(_cte() + " AND ticker = 'AAA' ORDER BY timestamp").fetchdf()
    assert d["vol_rel_20"].iloc[25] == pytest.approx(1.0)
    assert d["pm_vol_rel_20"].iloc[25] == pytest.approx(1.0)


def test_un_dia_de_diez_veces_el_volumen(con):
    v = [1000.0] * 30
    v[25] = 10_000.0
    _mete(con, "AAA", v)
    d = con.execute(_cte() + " AND ticker = 'AAA' ORDER BY timestamp").fetchdf()
    assert d["vol_rel_20"].iloc[25] == pytest.approx(10.0)


def test_el_dia_actual_no_entra_en_su_propia_media(con):
    """Con `ROWS BETWEEN 20 PRECEDING AND CURRENT ROW` un día de 10× saldría
    8,7× en vez de 10×: el propio día tira de la media hacia arriba."""
    v = [1000.0] * 30
    v[25] = 10_000.0
    _mete(con, "AAA", v)
    d = con.execute(_cte() + " AND ticker = 'AAA' ORDER BY timestamp").fetchdf()
    assert d["vol_rel_20"].iloc[25] == pytest.approx(10.0)      # NO 8,7
    assert d["vol_rel_20"].iloc[25] > 9.0


def test_el_primer_dia_no_tiene_con_que_comparar(con):
    _mete(con, "AAA", [1000.0] * 30)
    d = con.execute(_cte() + " AND ticker = 'AAA' ORDER BY timestamp").fetchdf()
    assert d["vol_rel_20"].isna().iloc[0]


def test_cada_ticker_lleva_su_media(con):
    _mete(con, "AAA", [1000.0] * 30)
    _mete(con, "BBB", [1_000_000.0] * 30)
    d = con.execute(_cte() + " ORDER BY ticker, timestamp").fetchdf()
    a = d[d["ticker"] == "AAA"]["vol_rel_20"].iloc[25]
    b = d[d["ticker"] == "BBB"]["vol_rel_20"].iloc[25]
    assert a == pytest.approx(1.0) and b == pytest.approx(1.0)


def test_los_tres_dias_previos(con):
    """«Volume 3 prev days vs 20d avg»: si los tres días anteriores fueron a
    5× lo normal, el ticker ya venía caliente."""
    v = [1000.0] * 30
    v[22] = v[23] = v[24] = 5000.0
    _mete(con, "AAA", v)
    d = con.execute(_cte() + " AND ticker = 'AAA' ORDER BY timestamp").fetchdf()
    # en el día 25, la media de los 3 previos es 5000; la de 20 días, más baja
    assert d["vol_prev3_rel_20"].iloc[25] > 2.5
    assert d["vol_prev3_rel_20"].iloc[10] == pytest.approx(1.0)


def test_el_filtro_de_fechas_no_estropea_la_media(con):
    """LA TRAMPA. Filtrando desde el día 26, el cociente de ese día tiene que
    seguir usando los 20 días anteriores, que quedan FUERA del rango pedido."""
    v = [1000.0] * 30
    v[25] = 10_000.0
    _mete(con, "AAA", v)
    d = con.execute(_cte() + " AND date >= '2025-01-26' ORDER BY timestamp").fetchdf()
    assert len(d) == 5
    assert d["vol_rel_20"].iloc[0] == pytest.approx(10.0), (
        "la media se ha calculado solo con los días del rango: el filtro se "
        "aplicó antes que la ventana")


def test_volumen_cero_no_revienta(con):
    _mete(con, "AAA", [0.0] * 25 + [5000.0] * 5)
    d = con.execute(_cte() + " AND ticker = 'AAA' ORDER BY timestamp").fetchdf()
    assert d["vol_rel_20"].iloc[24] is None or d["vol_rel_20"].isna().iloc[24]


# ══ Acciones en circulación y rotación (ASOF JOIN) ═════════════════════════

def _cte_con_circ(ruta_parquet: str | None) -> str:
    """La CTE con el hueco `__CIRCULACION__` resuelto, como hace el router."""
    c = _cte_cruda()
    if ruta_parquet:
        return c.replace("__CIRCULACION__",
                         f"SELECT ticker, CAST(fecha_informe AS DATE) AS fecha_informe, shares "
                         f"FROM read_parquet('{ruta_parquet}') WHERE shares > 0")
    return c.replace("__CIRCULACION__",
                     "SELECT NULL::VARCHAR AS ticker, NULL::DATE AS fecha_informe, "
                     "NULL::DOUBLE AS shares WHERE FALSE")


def test_la_rotacion_usa_el_informe_anterior(con, tmp_path):
    """La razón de ser del dato a fecha: estas empresas amplían capital cada
    dos por tres (OCTO pasó de 3,04 a 46,3 millones de acciones en seis
    meses). Con el número de HOY, un día de antes sale 15 veces mal."""
    import pandas as pd
    _mete(con, "AAA", [1_000_000.0] * 30)
    p = tmp_path / "circ.parquet"
    pd.DataFrame([
        {"ticker": "AAA", "fecha_informe": "2025-01-05", "shares": 1_000_000.0},
        {"ticker": "AAA", "fecha_informe": "2025-01-20", "shares": 10_000_000.0},
    ]).to_parquet(p)
    d = con.execute(_cte_con_circ(str(p).replace("\\", "/")) +
                    " AND ticker = 'AAA' ORDER BY timestamp").fetchdf()
    # día 10: manda el informe del 5 (1 M) -> rotación 1
    assert d["rotacion_dia"].iloc[9] == pytest.approx(1.0)
    # día 25: ya manda el del 20 (10 M) -> rotación 0,1
    assert d["rotacion_dia"].iloc[24] == pytest.approx(0.1)


def test_antes_del_primer_informe_no_hay_rotacion(con, tmp_path):
    import pandas as pd
    _mete(con, "AAA", [1_000_000.0] * 30)
    p = tmp_path / "circ.parquet"
    pd.DataFrame([{"ticker": "AAA", "fecha_informe": "2025-01-20", "shares": 1_000_000.0}]).to_parquet(p)
    d = con.execute(_cte_con_circ(str(p).replace("\\", "/")) +
                    " AND ticker = 'AAA' ORDER BY timestamp").fetchdf()
    assert d["rotacion_dia"].isna().iloc[5]      # no se rellena hacia atrás
    assert d["rotacion_dia"].iloc[25] == pytest.approx(1.0)


def test_sin_tabla_de_circulacion_la_consulta_sigue_funcionando(con):
    """Si el ETL no se ha pasado nunca, el resto de filtros tienen que seguir
    yendo; la rotación sale NULL y no deja pasar nada, que es lo correcto."""
    _mete(con, "AAA", [1000.0] * 30)
    d = con.execute(_cte_con_circ(None) + " AND ticker = 'AAA' ORDER BY timestamp").fetchdf()
    assert len(d) == 30
    assert d["rotacion_dia"].isna().all()
    assert d["vol_rel_20"].iloc[25] == pytest.approx(1.0)
