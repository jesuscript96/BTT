"""El MARGEN de un stop de estructura se puede optimizar.

EL FALLO (hasta el 7-sep-2026). En un stop «Market Structure» el campo `value`
guarda TEXTO ("PMH", "Previous Max"...). El extractor hacia `float(value)`, eso
reventaba, y se caia el bloque ENTERO del hard stop — incluido `offset_pct`,
que es un numero normal y corriente y ademas es la unica palanca real que tiene
ese stop. Consecuencia: una estrategia con stop estructural no ofrecia NI UNA
perilla del stop en el optimizador 3D, ni en el Walk Forward, ni en el
genetico. Los tres beben de `extract_parameters`. Y no daba error: el parametro
simplemente no salia en la lista.

Jaume, 7-sep-2026: «si hay una estrategia de estructura con % por encima de
PMH, no podria medirme ese % de distancia e ir probando?». Si, y no hacia falta
tocar el motor: `hs_offset_pct` ya viaja hasta los dos simuladores.

Lo que sigue SIN poder moverse es el NIVEL (PMH -> HOD...): son seis columnas
fijas en la firma del simulador y hay dos simuladores en paridad bit a bit.
Eso es otro trabajo.
"""
import copy

from app.services.optimization_service import extract_parameters, _set_nested_value


def _definicion(hard_stop):
    return {
        "bias": "long",
        "entry_logic": {"timeframe": "1m",
                        "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
        "exit_logic": {"timeframe": "1m",
                       "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
        "risk_management": {"hard_stop": hard_stop},
    }


def _por_ruta(params, ruta):
    return next((p for p in params if p["path"] == ruta), None)


def test_el_margen_del_stop_de_estructura_se_ofrece():
    d = _definicion({"type": "Market Structure", "value": "PMH", "offset_pct": 10})
    p = _por_ruta(extract_parameters(d), "risk_management.hard_stop.offset_pct")
    assert p is not None, "el margen sigue sin ofrecerse: el stop estructural no tiene perillas"
    assert p["current_value"] == 10.0
    assert p["min"] == 0.0
    assert p["max"] >= 15.0
    assert "PMH" in p["label"], "la etiqueta tiene que decir sobre QUE nivel es el margen"


def test_un_margen_de_cero_tambien_se_ofrece():
    """El 0 aqui NO es «desactivado»: es el stop clavado en el nivel, que es una
    configuracion normal. `_add` descarta los ceros a proposito (SL=0 es no
    tener stop), asi que este caso necesita el permiso explicito."""
    d = _definicion({"type": "Market Structure", "value": "Previous Max", "offset_pct": 0})
    p = _por_ruta(extract_parameters(d), "risk_management.hard_stop.offset_pct")
    assert p is not None, "con margen 0 el parametro desaparecia y no se podia empezar a barrer"
    assert p["current_value"] == 0.0


def test_sin_offset_en_la_definicion_se_asume_cero_y_se_ofrece():
    """Las estrategias viejas no llevan el campo. Si no se ofreciera, seguirian
    sin poder optimizar el stop y el arreglo no serviria para ellas."""
    d = _definicion({"type": "Market Structure", "value": "HOD"})
    p = _por_ruta(extract_parameters(d), "risk_management.hard_stop.offset_pct")
    assert p is not None
    assert p["current_value"] == 0.0


def test_el_nivel_sigue_sin_ofrecerse():
    """Es texto y el simulador solo entiende seis niveles fijos. Ofrecerlo como
    numero seria peor que no ofrecerlo."""
    d = _definicion({"type": "Market Structure", "value": "PMH", "offset_pct": 5})
    assert _por_ruta(extract_parameters(d), "risk_management.hard_stop.value") is None


def test_el_stop_porcentual_no_cambia():
    """Regresion: lo de siempre tiene que seguir igual, y sin margen de mas."""
    d = _definicion({"type": "Percentage", "value": 15})
    params = extract_parameters(d)
    val = _por_ruta(params, "risk_management.hard_stop.value")
    assert val is not None and val["current_value"] == 15.0
    assert _por_ruta(params, "risk_management.hard_stop.offset_pct") is None, (
        "un stop porcentual no tiene nivel: el margen ahi no significa nada")


def test_use_hard_stop_desactivado_sigue_mandando():
    d = _definicion({"type": "Market Structure", "value": "PMH", "offset_pct": 10})
    d["risk_management"]["use_hard_stop"] = False
    assert _por_ruta(extract_parameters(d), "risk_management.hard_stop.offset_pct") is None


def test_la_ruta_escribe_donde_el_motor_lo_lee():
    """La otra mitad del contrato: que el punto de la rejilla aterrice en el
    sitio del que el motor saca `hs_offset_pct`."""
    d = _definicion({"type": "Market Structure", "value": "PMH", "offset_pct": 10})
    nueva = copy.deepcopy(d)
    _set_nested_value(nueva, "risk_management.hard_stop.offset_pct", 7.5)
    assert nueva["risk_management"]["hard_stop"]["offset_pct"] == 7.5
    assert d["risk_management"]["hard_stop"]["offset_pct"] == 10, "no se toca el original"


def test_el_motor_lo_lee_de_verdad():
    """Sin esto, el parametro seria un ajuste fantasma perfecto: aparece en la
    lista, se barre, y el backtest sale identico. Se comprueba sobre el fuente
    porque ejecutar un backtest aqui pide el lago."""
    from pathlib import Path
    svc = Path(__file__).resolve().parents[1] / "app" / "services"
    assert 'hs.get("offset_pct"' in (svc / "backtest_service.py").read_text(encoding="utf-8")
    assert "hs_offset_pct" in (svc / "portfolio_sim.py").read_text(encoding="utf-8")
    assert "hs_offset_pct" in (svc / "sim_dispatch.py").read_text(encoding="utf-8")


def test_el_genetico_tambien_lo_ve():
    """El modo mejorar saca sus genes del mismo extractor; si no llegara, el
    arreglo se quedaria a medias justo donde Jaume lo pidio."""
    d = _definicion({"type": "Market Structure", "value": "PMH", "offset_pct": 10})
    rutas = {p["path"] for p in extract_parameters(d)}
    assert "risk_management.hard_stop.offset_pct" in rutas
