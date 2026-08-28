"""El optimizador tiene que aceptar Take Profit por TIEMPO y por HORA (V29).

Reportado por Valeri: "sin TP% no deja optimizar". Quien cierra por horario tiene
take_profit.value = "15:30" (texto), y extract_parameters hacia float("15:30") sin
protegerlo: ValueError. No fallaba solo ese parametro — reventaba la extraccion
ENTERA, asi que el optimizador quedaba inservible para esa gente. El workaround
que usaban (SL parcial 1% + salida por hora 99%) falseaba los resultados.

El barrido es numerico, asi que por hora se recorre en MINUTOS DESDE MEDIANOCHE y
al escribir cada punto se devuelve la forma original ("15:30"): el motor no cambia.
"""
import pytest

from app.services.optimization_service import extract_parameters


def _tp_full(tipo, valor):
    return {"risk_management": {"use_take_profit": True, "take_profit_mode": "Full",
                                "take_profit": {"type": tipo, "value": valor}}}


def _tp_parcial(distance_pct):
    return {"risk_management": {"use_take_profit": True, "take_profit_mode": "Partial",
                                "partial_take_profits": [{"distance_pct": distance_pct,
                                                          "capital_pct": 50}]}}


def _por_path(params, fragmento):
    return [p for p in params if fragmento in (p.get("path") or "")]


def test_tp_por_hora_no_revienta_la_extraccion():
    """La regresion exacta: antes lanzaba ValueError y no se podia optimizar nada."""
    params = extract_parameters(_tp_full("Hour", "15:30"))
    assert params, "la extraccion devolvio vacio; el optimizador seguiria sin ser usable"


def test_tp_por_hora_se_barre_en_minutos_desde_medianoche():
    (tp,) = _por_path(extract_parameters(_tp_full("Hour", "15:30")), "take_profit.value")
    assert tp["current_value"] == 930          # 15:30
    assert tp["unit"] == "time_of_day"
    # Acotado a la sesion del lago (04:00-20:00), no a las 3 de la manana.
    assert tp["min"] >= 4 * 60
    assert tp["max"] <= 20 * 60
    assert tp["min"] < tp["current_value"] < tp["max"]


def test_tp_por_tiempo_se_barre_en_minutos_enteros():
    """Antes heredaba el paso de los porcentajes (0,5) = medios minutos."""
    (tp,) = _por_path(extract_parameters(_tp_full("Time", 30)), "take_profit.value")
    assert tp["current_value"] == 30
    assert tp["unit"] == "minutes"
    assert float(tp["step"]).is_integer() and tp["step"] >= 1


def test_tp_por_porcentaje_sigue_igual():
    (tp,) = _por_path(extract_parameters(_tp_full("Pct", 10)), "take_profit.value")
    assert tp["current_value"] == 10
    assert tp["min"] == pytest.approx(0.5)


@pytest.mark.parametrize("distancia", ["HOUR:15:30", "TIME:30", 2.5])
def test_parciales_optimizables_no_revientan(distancia):
    params = extract_parameters(_tp_parcial(distancia))
    assert _por_path(params, "partial_take_profits.0.distance_pct")


def test_parcial_al_cierre_no_es_optimizable_pero_no_rompe():
    """'EOD' no es un numero: se omite ese parametro, pero el capital % sigue ahi."""
    params = extract_parameters(_tp_parcial("EOD"))
    assert not _por_path(params, "partial_take_profits.0.distance_pct")
    assert _por_path(params, "partial_take_profits.0.capital_pct")
