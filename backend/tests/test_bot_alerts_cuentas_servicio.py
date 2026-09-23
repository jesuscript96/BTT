"""Las «otras cuentas» del cuadro de mandos: normalizacion y viaje completo
(guardar -> leer -> vigiladas) en una base DuckDB de prueba (18-sep-2026)."""
import duckdb

from app.services import bot_alerts_service as bas


def test_limpiar_cuentas_normaliza_y_descarta_lo_invalido():
    out = bas.limpiar_cuentas([
        {"nombre": " IBKR ", "riesgo_usd": 200, "riesgo_piramide_usd": 150},
        {"nombre": "", "riesgo_usd": "250", "riesgo_piramide_usd": None},
        {"nombre": "sin riesgo", "riesgo_usd": 0},
        {"nombre": "roto", "riesgo_usd": "x"},
        "basura",
    ])
    assert out == [
        {"nombre": "IBKR", "riesgo_usd": 200.0, "riesgo_piramide_usd": 150.0},
        {"nombre": "cuenta 3", "riesgo_usd": 250.0, "riesgo_piramide_usd": None},
    ]
    assert bas.limpiar_cuentas([]) is None and bas.limpiar_cuentas(None) is None
    assert bas.limpiar_cuentas([{"riesgo_usd": 0}]) is None


def test_set_watch_guarda_y_get_watch_devuelve_las_cuentas():
    con = duckdb.connect(":memory:")
    bas._DDL_DONE = False
    fila = bas.set_watch(con, "s1", True, 300.0, riesgo_piramide_usd=300.0,
                         cuentas=[{"nombre": "IBKR", "riesgo_usd": 200, "riesgo_piramide_usd": None}])
    assert fila["cuentas"] == [{"nombre": "IBKR", "riesgo_usd": 200.0, "riesgo_piramide_usd": None}]
    leido = bas.get_watch(con)["s1"]
    assert leido["cuentas"] == fila["cuentas"]
    assert leido["riesgo_usd"] == 300.0
    # Guardar sin cuentas las borra (quitar una cuenta tambien es guardar).
    bas.set_watch(con, "s1", True, 300.0, cuentas=[])
    assert bas.get_watch(con)["s1"]["cuentas"] is None
    bas._DDL_DONE = False
