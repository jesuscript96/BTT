"""Modo «mejorar» del genético: la familia de pivotes y los niveles base
(21-sep-2026).

Jaume: «no tiene en cuenta indicadores como el pico/valle (nºN) o el Ultimo
pivote, previous max y min, Prev. Bar close/open/high/low, el de recorrido...».
En modo mejorar los genes salen de `extract_parameters`, que no sacaba
`pivot_window` ni `pivot_rank` (→ una estrategia con «Pico nº2» no tenía nada
que mover), proponía rangos 0…8 para objetivos NEGATIVOS («Recorrido (%) <
-2» se barría en positivo), y un nivel sin parámetros (Prev. Bar Low) no tenía
ningún gen. Los tres se prueban aquí sin backtests.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.services.optimization_service import extract_parameters, _set_nested_value  # noqa: E402


def _cond(src, comp, tgt):
    return {"type": "indicator_comparison", "source": src, "comparator": comp,
            "target": tgt, "timeframe": "1m"}


def _estrategia(*conds):
    return {
        "bias": "short",
        "entry_logic": {"timeframe": "1m",
                        "root_condition": {"type": "group", "operator": "AND",
                                           "conditions": list(conds)}},
        "risk_management": {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 5},
                            "use_take_profit": True, "take_profit": {"type": "Percentage", "value": 10}},
    }


def _por_path(params):
    return {p["path"]: p for p in params}


def test_pico_contra_pico_saca_ventana_y_numero_de_giro_de_los_dos_lados():
    d = _estrategia(_cond({"name": "Pico", "pivot_window": 3, "swing_dir": "up", "pivot_rank": 1},
                          "LESS_THAN",
                          {"name": "Pico", "pivot_window": 3, "swing_dir": "up", "pivot_rank": 2}))
    pp = _por_path(extract_parameters(d))
    base = "entry_logic.root_condition.conditions.0"
    for lado in ("source", "target"):
        pw = pp[f"{base}.{lado}.pivot_window"]
        pr = pp[f"{base}.{lado}.pivot_rank"]
        assert pw["min"] == 1 and pw["max"] == 8 and pw["step"] == 1
        assert pr["min"] == 1 and pr["max"] == 6 and pr["step"] == 1
    assert pp[f"{base}.source.pivot_rank"]["current_value"] == 1
    assert pp[f"{base}.target.pivot_rank"]["current_value"] == 2


def test_edad_y_volumen_del_pico_y_ultimo_pivote_tambien():
    d = _estrategia(
        _cond({"name": "Edad del pico", "pivot_window": 2, "swing_dir": "down", "pivot_rank": 3}, "LESS_THAN", 90),
        _cond({"name": "Bar Close"}, "CROSSES_BELOW", {"name": "Ultimo pivote", "pivot_window": 5, "swing_dir": "down"}),
    )
    pp = _por_path(extract_parameters(d))
    assert "entry_logic.root_condition.conditions.0.source.pivot_rank" in pp
    assert "entry_logic.root_condition.conditions.0.source.pivot_window" in pp
    assert pp["entry_logic.root_condition.conditions.0.target"]["current_value"] == 90
    assert "entry_logic.root_condition.conditions.1.target.pivot_window" in pp
    # «Ultimo pivote» no tiene numero de giro: no se inventa
    assert "entry_logic.root_condition.conditions.1.target.pivot_rank" not in pp


def test_el_pivot_rank_se_escribe_como_entero():
    d = _estrategia(_cond({"name": "Pico", "pivot_window": 3, "swing_dir": "up", "pivot_rank": 1},
                          "LESS_THAN", {"name": "Pico", "pivot_window": 3, "swing_dir": "up", "pivot_rank": 2}))
    _set_nested_value(d, "entry_logic.root_condition.conditions.0.target.pivot_rank", 3.0)
    v = d["entry_logic"]["root_condition"]["conditions"][0]["target"]["pivot_rank"]
    assert v == 3 and isinstance(v, int)


def test_un_objetivo_negativo_se_barre_en_negativo():
    """«Recorrido (%) < -2»: antes el rango propuesto era 0…8 (max(0, v·0,25) y
    max(3v, v+10)), o sea que el 3D y el genético nunca probaban un valor con
    el signo que la condición pedía."""
    d = _estrategia(_cond({"name": "Recorrido (%)"}, "LESS_THAN", -2))
    p = _por_path(extract_parameters(d))["entry_logic.root_condition.conditions.0.target"]
    assert p["current_value"] == -2
    assert p["max"] < 0 and p["min"] < p["max"], p
    assert p["min"] == -12 and p["max"] == -0.5
    assert p["step"] == 0.5          # el paso de un -2 es el de un 2


def test_un_objetivo_positivo_sigue_igual_que_siempre():
    d = _estrategia(_cond({"name": "Recorrido (%)"}, "GREATER_THAN", 2))
    p = _por_path(extract_parameters(d))["entry_logic.root_condition.conditions.0.target"]
    assert (p["min"], p["max"], p["step"]) == (0.5, 12, 0.5)


def test_el_nivel_de_destino_es_un_gen_categorico_en_el_router():
    from app.routers.genetico import _genes_extra
    d = _estrategia(
        _cond({"name": "Bar Close", "offset": 0}, "LESS_THAN", {"name": "Prev. Bar Low", "offset": 0}),
        _cond({"name": "Bar Close"}, "CROSSES_BELOW", {"name": "SMA", "period": 20}),
        _cond({"name": "RSI", "period": 14}, "GREATER_THAN", 70),
    )
    genes = {g["path"]: g for g in _genes_extra(d)}
    g = genes["entry_logic.root_condition.conditions.0.target.name"]
    assert g["current_value"] == "Prev. Bar Low" and g["bloque"] == "entrada"
    assert {"Prev. Bar Close", "Previous max", "VWAP", "PM High"} <= set(g["opciones"])
    # una SMA como destino no se ofrece cambiar por un nivel: es otra idea
    assert "entry_logic.root_condition.conditions.1.target.name" not in genes
    assert "entry_logic.root_condition.conditions.2.target.name" not in genes


def test_el_gen_del_nivel_se_aplica_en_afinar():
    from app.routers.genetico import _genes_extra
    from genetico import afinar
    d = _estrategia(_cond({"name": "Bar Close", "offset": 0}, "LESS_THAN", {"name": "Prev. Bar Low", "offset": 0}))
    gen = next(g for g in _genes_extra(d) if g["path"].endswith(".target.name"))
    cfg = {"modo": "mejorar", "estrategia_base": d, "genes": [gen]}
    ind = {"valores": {gen["id"]: "Prev. Bar Close"}}
    out = afinar.a_definicion(ind, cfg)
    tgt = out["entry_logic"]["root_condition"]["conditions"][0]["target"]
    assert tgt["name"] == "Prev. Bar Close" and tgt["offset"] == 0
    # y la semilla sigue intacta
    assert d["entry_logic"]["root_condition"]["conditions"][0]["target"]["name"] == "Prev. Bar Low"
