"""Los limites horarios de entrada se pueden OPTIMIZAR.

Antes (hasta el 2026-09-06) `entry_logic.entry_time_windows` no aparecia en la
lista de parametros barribles: los valores son texto ("09:30"), `float()`
revienta y `_add` los descartaba en silencio. No habia error, no habia log; el
parametro simplemente no estaba en el desplegable del optimizador 3D.

Se barren en MINUTOS DESDE MEDIANOCHE (09:30 = 570) y al escribir cada punto de
la rejilla se devuelve el texto "HH:MM", igual que el take profit por hora.
"""
import copy

from app.services.optimization_service import (
    extract_parameters, _set_nested_value, _param_unit_from_def,
)


def _definicion(ventanas):
    return {
        "bias": "long",
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {"type": "group", "operator": "AND", "conditions": []},
            "entry_time_windows": ventanas,
        },
        "exit_logic": {"timeframe": "1m",
                       "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
        "risk_management": {},
    }


def _por_ruta(params, ruta):
    return next((p for p in params if p["path"] == ruta), None)


def test_la_ventana_aparece_como_dos_parametros():
    d = _definicion([{"from_time": "09:30", "to_time": "11:30"}])
    params = extract_parameters(d)

    desde = _por_ruta(params, "entry_logic.entry_time_windows.0.from_time")
    hasta = _por_ruta(params, "entry_logic.entry_time_windows.0.to_time")
    assert desde is not None and hasta is not None

    assert desde["current_value"] == 570  # 09:30
    assert hasta["current_value"] == 690  # 11:30
    assert desde["unit"] == hasta["unit"] == "time_of_day"
    assert desde["category"] == "Entry"


def test_el_rango_propuesto_no_se_sale_de_la_sesion_del_lago():
    """+-2h alrededor del valor actual, recortado a 04:00-20:00."""
    d = _definicion([{"from_time": "04:30", "to_time": "19:30"}])
    params = extract_parameters(d)
    desde = _por_ruta(params, "entry_logic.entry_time_windows.0.from_time")
    hasta = _por_ruta(params, "entry_logic.entry_time_windows.0.to_time")
    assert desde["min"] == 4 * 60
    assert hasta["max"] == 20 * 60


def test_al_escribir_un_punto_vuelve_a_ser_texto():
    """EL PUNTO CRITICO: el barrido mueve numeros, la definicion guarda 'HH:MM'.

    Si esto se rompe, el motor recibe `to_time = 655.0`, `str(655.0).split(':')`
    falla y la ventana se descarta entera — sin excepcion y sin log: la corrida
    saldria como si no hubiera limite horario.
    """
    d = _definicion([{"from_time": "09:30", "to_time": "11:30"}])
    mod = copy.deepcopy(d)
    _set_nested_value(mod, "entry_logic.entry_time_windows.0.to_time", 655.0)
    assert mod["entry_logic"]["entry_time_windows"][0]["to_time"] == "10:55"
    # La otra punta de la ventana no se toca.
    assert mod["entry_logic"]["entry_time_windows"][0]["from_time"] == "09:30"


def test_la_unidad_hace_que_el_barrido_sea_de_minutos_enteros():
    """`_param_unit_from_def` es lo que fuerza `is_int` en la rejilla."""
    d = _definicion([{"from_time": "09:30", "to_time": "11:30"}])
    assert _param_unit_from_def(d, "entry_logic.entry_time_windows.0.from_time") == "time_of_day"
    # Y no se contagia a rutas que no son ventanas.
    assert _param_unit_from_def(d, "risk_management.hard_stop.value") is None


def test_varias_ventanas_se_numeran():
    d = _definicion([{"from_time": "09:30", "to_time": "10:30"},
                     {"from_time": "14:00", "to_time": "15:00"}])
    params = extract_parameters(d)
    etiquetas = {p["path"]: p["label"] for p in params}
    assert etiquetas["entry_logic.entry_time_windows.0.from_time"] == "Ventana de entrada (desde)"
    assert etiquetas["entry_logic.entry_time_windows.1.from_time"] == "Ventana de entrada 2 (desde)"


def test_sin_ventanas_no_aparece_nada_nuevo():
    """Regla nº1: una estrategia sin limite horario da la misma lista de antes."""
    params = extract_parameters(_definicion([]))
    assert not [p for p in params if "entry_time_windows" in p["path"]]


def test_eje_enlazado_mueve_la_ventana_entera():
    """Barrido por FRANJAS: un solo numero mueve las dos puntas de la ventana.

    Es lo que alimenta el grafico de «EV barriendo la ventana»: 09:30-10:00,
    10:00-10:30, ... con una sola dimension de rejilla (N corridas, no N**2).
    """
    from app.services.optimization_service import apply_point_to_def

    eje = {
        "id": "franja", "label": "Franja de entrada",
        "path": "entry_logic.entry_time_windows.0.from_time",
        "linked_paths": ["entry_logic.entry_time_windows.0.to_time"],
        "linked_offsets": [30],
    }
    d = _definicion([{"from_time": "09:30", "to_time": "10:00"}])

    mod = copy.deepcopy(d)
    apply_point_to_def(mod, [eje], (630.0,))  # 10:30
    assert mod["entry_logic"]["entry_time_windows"][0] == {
        "from_time": "10:30", "to_time": "11:00"
    }

    mod2 = copy.deepcopy(d)
    apply_point_to_def(mod2, [eje], (570.0,))  # 09:30
    assert mod2["entry_logic"]["entry_time_windows"][0] == {
        "from_time": "09:30", "to_time": "10:00"
    }


def test_un_eje_sin_enlazar_se_comporta_como_siempre():
    """Regla nº1: los ejes de toda la vida no ven ningun cambio."""
    from app.services.optimization_service import apply_point_to_def

    d = {"risk_management": {"hard_stop": {"value": 10}}}
    apply_point_to_def(d, [{"id": "sl", "path": "risk_management.hard_stop.value"}], (7.5,))
    assert d["risk_management"]["hard_stop"]["value"] == 7.5
