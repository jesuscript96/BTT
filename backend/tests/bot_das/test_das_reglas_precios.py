"""reglas/precios.py: Decimal siempre, punto medio de R-B-01 v3, techos permisivos, tramo y tabla de rutas por hora."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.bot_das.reglas import precios
from app.bot_das.reglas.precios import (
    ACCIONES_RUTA, bajo_bid, con_techo, de_float, distancia_pct, punto_medio_abajo, punto_medio_arriba,
    redondear_abajo, redondear_arriba, ruta, subida_pct, tramo,
)
from app.bot_das.reloj import ET

D = Decimal
RUTA_CONFIG = Path(__file__).parent / "fixtures" / "config_ejemplo.json"


@pytest.fixture(scope="module")
def cfg_rutas() -> dict:
    return json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))["rutas"]


def _hora(hh: int, mm: int) -> datetime:
    return datetime(2026, 9, 25, hh, mm, tzinfo=ET)


# ── de_float (injerto A §8.1, riesgo 12) ────────────────────────────────
@pytest.mark.parametrize("entrada,esperado", [
    pytest.param(3.45, D("3.45"), id="float"),
    pytest.param(0.1, D("0.1"), id="0.1-sin-cola-binaria"),
    pytest.param(1199.0, D("1199.0"), id="acciones-del-Evento-l.1208"),
    pytest.param(5, D("5"), id="int"),
    pytest.param("0.1234", D("0.1234"), id="texto"),
    pytest.param(" 10.30 ", D("10.30"), id="texto-con-espacios"),
    pytest.param(D("7.77"), D("7.77"), id="Decimal-pasa-tal-cual"),
    pytest.param(0.1 + 0.2, D("0.30000000000000004"), id="float-fiel-al-repr"),
])
def test_de_float(entrada, esperado):
    resultado = de_float(entrada)
    assert resultado == esperado and type(resultado) is Decimal


@pytest.mark.parametrize("entrada", [
    pytest.param(float("nan"), id="NaN"),
    pytest.param(float("inf"), id="inf"),
    pytest.param(float("-inf"), id="-inf"),
    pytest.param(None, id="None"),
    pytest.param(True, id="bool"),
    pytest.param("nan", id="texto-nan"),
    pytest.param("Infinity", id="texto-inf"),
    pytest.param("abc", id="texto-no-numerico"),
    pytest.param("", id="texto-vacio"),
    pytest.param(D("NaN"), id="Decimal-NaN"),
    pytest.param([1.0], id="lista"),
])
def test_de_float_rechaza(entrada):
    with pytest.raises(ValueError):
        de_float(entrada)


# ── redondeos ───────────────────────────────────────────────────────────
def test_redondear_delegan_en_al_tick():
    assert redondear_arriba(D("1.005")) == D("1.01") and redondear_abajo(D("1.005")) == D("1.00")
    assert redondear_arriba(D("0.12345")) == D("0.1235") and redondear_abajo(D("0.12345")) == D("0.1234")


# ── punto medio (R-B-01 v3, 24-sep) ─────────────────────────────────────
@pytest.mark.parametrize("bid,ask,esperado", [
    pytest.param(D("10.00"), D("10.01"), D("10.01"), id="R-B-01-v3-spread-1-tick->ask"),
    pytest.param(D("10.00"), D("10.02"), D("10.01"), id="R-B-01-v3-spread-2-ticks->bid+1"),
    pytest.param(D("10.00"), D("10.03"), D("10.02"), id="R-B-01-v3-spread-3-ticks->ceil"),
    pytest.param(D("10.00"), D("10.10"), D("10.05"), id="spread-10-ticks-medio-exacto"),
    pytest.param(D("10.00"), D("10.00"), D("10.00"), id="spread-0->ask"),
    pytest.param(D("0.5000"), D("0.5001"), D("0.5001"), id="penny-1-tick-0.0001->ask"),
    pytest.param(D("0.5000"), D("0.5002"), D("0.5001"), id="penny-2-ticks->bid+0.0001"),
    pytest.param(D("0.5000"), D("0.5003"), D("0.5002"), id="penny-3-ticks->ceil"),
    pytest.param(D("0.9999"), D("1.0001"), D("1.00"), id="cruza-el-dolar"),
    pytest.param(D("3.44"), D("3.46"), D("3.45"), id="ejemplo-del-diario-§8"),
])
def test_punto_medio_arriba(bid, ask, esperado):
    resultado = punto_medio_arriba(bid, ask)
    assert resultado == esperado and type(resultado) is Decimal
    assert resultado > bid or ask == bid                       # agrega: nunca ≤ bid con spread > 0


@pytest.mark.parametrize("bid,ask,esperado", [
    pytest.param(D("10.00"), D("10.01"), D("10.00"), id="spread-1-tick->bid"),
    pytest.param(D("10.00"), D("10.02"), D("10.01"), id="spread-2-ticks->ask-1"),
    pytest.param(D("10.00"), D("10.03"), D("10.01"), id="spread-3-ticks->floor"),
    pytest.param(D("0.5000"), D("0.5003"), D("0.5001"), id="penny-3-ticks->floor"),
])
def test_punto_medio_abajo(bid, ask, esperado):
    resultado = punto_medio_abajo(bid, ask)
    assert resultado == esperado and type(resultado) is Decimal
    assert resultado < ask                                     # una compra que agrega queda bajo el ask


@pytest.mark.parametrize("bid,ask", [
    pytest.param(D("10.02"), D("10.00"), id="libro-cruzado"),
    pytest.param(D("0"), D("10.00"), id="bid-cero"),
    pytest.param(D("10.00"), D("-1"), id="ask-menor-que-cero"),
    pytest.param(D("NaN"), D("10.00"), id="bid-NaN"),
])
def test_punto_medio_rechaza_libros_invalidos(bid, ask):
    with pytest.raises(ValueError):
        punto_medio_arriba(bid, ask)
    with pytest.raises(ValueError):
        punto_medio_abajo(bid, ask)


# ── techos y suelos ─────────────────────────────────────────────────────
@pytest.mark.parametrize("precio,pct,arriba,esperado", [
    pytest.param(D("10.00"), D("3"), True, D("10.30"), id="R-D-03-v2-techo-compra-exacto"),
    pytest.param(D("10.01"), D("3"), True, D("10.32"), id="R-D-03-v2-techo-compra-ceil-permisivo"),
    pytest.param(D("10.01"), D("3"), False, D("9.70"), id="suelo-venta-floor-permisivo"),
    pytest.param(D("10.00"), D("5"), True, D("10.50"), id="R-D-06-techo-5%"),
    pytest.param(D("0.5000"), D("3"), True, D("0.5150"), id="penny-techo-exacto"),
    pytest.param(D("0.5001"), D("3"), True, D("0.5152"), id="penny-techo-ceil"),
    pytest.param(D("10.00"), D("0"), True, D("10.00"), id="pct-0"),
    pytest.param(D("10.00"), D("13"), True, D("11.30"), id="R-C-01-v3-emergencia-disparo-L+13%"),
    pytest.param(D("10.00"), D("63"), True, D("16.30"), id="R-C-01-v3-emergencia-limite-L+63%"),
])
def test_con_techo(precio, pct, arriba, esperado):
    resultado = con_techo(precio, pct, arriba)
    assert resultado == esperado and type(resultado) is Decimal


def test_con_techo_rechaza():
    with pytest.raises(ValueError):
        con_techo(D("10.00"), D("-1"), True)
    with pytest.raises(ValueError):
        con_techo(D("0"), D("3"), True)
    with pytest.raises(ValueError):
        con_techo(D("10.00"), D("NaN"), True)


@pytest.mark.parametrize("bid,pct,esperado", [
    pytest.param(D("10.00"), D("0.5"), D("9.95"), id="R-B-01-v3-cruce-bid-0.5%-exacto"),
    pytest.param(D("10.01"), D("0.5"), D("9.95"), id="R-B-01-v3-cruce-floor"),
    pytest.param(D("0.5001"), D("0.5"), D("0.4975"), id="penny-cruce-floor"),
    pytest.param(D("3.44"), D("0.5"), D("3.42"), id="3.44->3.4228->3.42"),
])
def test_bajo_bid(bid, pct, esperado):
    resultado = bajo_bid(bid, pct)
    assert resultado == esperado and type(resultado) is Decimal and resultado < bid


# ── tramo y ruta (tabla de rutas 24-sep, regla 612) ─────────────────────
@pytest.mark.parametrize("precio,esperado", [
    pytest.param(D("1"), "ge_1", id="1$"), pytest.param(D("1.00"), "ge_1", id="1.00$"),
    pytest.param(D("100"), "ge_1", id="100$"), pytest.param(D("0.9999"), "lt_1", id="0.9999$"),
    pytest.param(D("0.0001"), "lt_1", id="0.0001$"),
])
def test_tramo(precio, esperado):
    assert tramo(precio) == esperado


@pytest.mark.parametrize("accion,precio,hora,esperado", [
    pytest.param("agregar", D("3.45"), _hora(9, 30), "SAGEREB", id="agregar-ge1->SAGEREB"),
    pytest.param("agregar", D("0.45"), _hora(9, 30), "MIAX", id="agregar-lt1->MIAX"),
    pytest.param("agregar", D("0.45"), _hora(4, 0), "MIAX", id="agregar-lt1-04:00->MIAX"),
    pytest.param("cruzar", D("3.45"), _hora(4, 0), "SAGEPRO", id="cruzar-ge1-04:00->SAGEPRO"),
    pytest.param("cruzar", D("3.45"), _hora(15, 59), "SAGEPRO", id="cruzar-ge1-RTH->SAGEPRO"),
    pytest.param("cruzar", D("0.45"), _hora(6, 59), "MIAX", id="cruzar-lt1-06:59->MIAX-(EDGA-cerrada)"),
    pytest.param("cruzar", D("0.45"), _hora(7, 0), "EDGA", id="cruzar-lt1-07:00->EDGA"),
    pytest.param("cruzar", D("0.45"), _hora(9, 30), "EDGA", id="cruzar-lt1-09:30->EDGA"),
    pytest.param("cruzar", D("0.45"), _hora(4, 0), "MIAX", id="cruzar-lt1-04:00->MIAX"),
    pytest.param("stop", D("3.45"), _hora(9, 30), "STOP", id="stop->STOP-R-C-01"),
    pytest.param("stop", D("0.45"), _hora(4, 30), "STOP", id="stop-penny->STOP"),
    pytest.param("halt", D("3.45"), _hora(9, 30), "OPEN", id="halt->OPEN-EP-2"),
])
def test_ruta(cfg_rutas, accion, precio, hora, esperado):
    assert ruta(cfg_rutas, accion, precio, hora) == esperado


def test_ruta_rechaza_accion_desconocida_y_ruta_sin_configurar(cfg_rutas):
    assert ACCIONES_RUTA == ("agregar", "cruzar", "stop", "halt")
    with pytest.raises(ValueError):
        ruta(cfg_rutas, "comprar", D("3.45"), _hora(9, 30))
    incompleta = {"agregar": {"ge_1": "SAGEREB"}, "cruzar": {"ge_1": "SAGEPRO", "lt_1_desde_0700": ""}}
    with pytest.raises(ValueError):
        ruta(incompleta, "agregar", D("0.45"), _hora(9, 30))          # falta lt_1
    with pytest.raises(ValueError):
        ruta(incompleta, "cruzar", D("0.45"), _hora(9, 30))           # vacía
    with pytest.raises(ValueError):
        ruta(incompleta, "stop", D("3.45"), _hora(9, 30))             # falta stop
    with pytest.raises(ValueError):
        ruta({"stop": {"ruta": "STOP"}}, "stop", D("3.45"), _hora(9, 30))   # no es texto


def test_ruta_acepta_hora_naive_ya_en_et(cfg_rutas):
    assert ruta(cfg_rutas, "cruzar", D("0.45"), datetime(2026, 9, 25, 6, 59)) == "MIAX"
    assert ruta(cfg_rutas, "cruzar", D("0.45"), datetime(2026, 9, 25, 7, 0)) == "EDGA"


def test_L0_04_ruta_convierte_a_et_una_hora_aware_en_otra_zona(cfg_rutas):
    """L0-04: 11:30 UTC = 07:30 ET → EDGA; 10:30 UTC = 06:30 ET → MIAX (EDGA cerrada); Madrid 13:30 = 07:30 ET."""
    from datetime import timezone
    from zoneinfo import ZoneInfo

    assert ruta(cfg_rutas, "cruzar", D("0.45"), datetime(2026, 9, 25, 11, 30, tzinfo=timezone.utc)) == "EDGA"
    assert ruta(cfg_rutas, "cruzar", D("0.45"), datetime(2026, 9, 25, 10, 30, tzinfo=timezone.utc)) == "MIAX"
    madrid = ZoneInfo("Europe/Madrid")
    assert ruta(cfg_rutas, "cruzar", D("0.45"), datetime(2026, 9, 25, 13, 30, tzinfo=madrid)) == "EDGA"
    assert ruta(cfg_rutas, "cruzar", D("0.45"), datetime(2026, 9, 25, 12, 30, tzinfo=madrid)) == "MIAX"
    assert ruta(cfg_rutas, "cruzar", D("0.45"), datetime(2026, 9, 25, 7, 0, tzinfo=ET)) == "EDGA"


# ── distancias ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("a,b,esperado", [
    pytest.param(D("10.30"), D("10"), D("3"), id="+3%"),
    pytest.param(D("9.70"), D("10"), D("-3"), id="-3%"),
    pytest.param(D("10"), D("10"), D("0"), id="0%"),
    pytest.param(D("3.45"), D("3.44"), D("0.29"), id="R-A-01-retraso-0.29%-(redondeado)"),
])
def test_distancia_pct(a, b, esperado):
    resultado = distancia_pct(a, b)
    assert resultado.quantize(D("0.01")) == esperado and type(resultado) is Decimal


def test_subida_pct_y_referencia_cero():
    assert subida_pct(D("10"), D("35")) == D("250")            # R-F-05: T1 +250 %
    assert subida_pct(D("10"), D("11.30")) == D("13")           # emergencia +13 %
    with pytest.raises(ValueError):
        distancia_pct(D("1"), D("0"))
    with pytest.raises(ValueError):
        subida_pct(D("NaN"), D("1"))


# ── nunca aparece un float en los resultados ────────────────────────────
@pytest.mark.parametrize("llamada", [
    pytest.param(lambda: de_float(3.45), id="de_float"),
    pytest.param(lambda: redondear_arriba(D("1.005")), id="redondear_arriba"),
    pytest.param(lambda: redondear_abajo(D("1.005")), id="redondear_abajo"),
    pytest.param(lambda: punto_medio_arriba(D("3.44"), D("3.46")), id="punto_medio_arriba"),
    pytest.param(lambda: punto_medio_abajo(D("3.44"), D("3.46")), id="punto_medio_abajo"),
    pytest.param(lambda: con_techo(D("3.45"), D("3"), True), id="con_techo"),
    pytest.param(lambda: bajo_bid(D("3.45"), D("0.5")), id="bajo_bid"),
    pytest.param(lambda: distancia_pct(D("3.45"), D("3.44")), id="distancia_pct"),
    pytest.param(lambda: subida_pct(D("3.44"), D("3.45")), id="subida_pct"),
])
def test_resultados_son_decimal(llamada):
    resultado = llamada()
    assert type(resultado) is Decimal and resultado.is_finite()


def test_modulo_es_puro():
    """Sin reloj ni I/O: nada de `time`, `datetime.now`, `os` ni `logging` en el módulo (§3, reglas/*)."""
    fuente = Path(precios.__file__).read_text(encoding="utf-8")
    for prohibido in ("import time", "datetime.now", "import os", "import logging", "open(", "os.environ"):
        assert prohibido not in fuente
