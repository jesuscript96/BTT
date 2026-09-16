"""CAMINO DE CONDICIONES en piramidación — P0: schema + compilador
(PRD 2026-09-16, docs/PRD_CAMINITO_CONDICIONES_PIRAMIDACION_20260916.md §5-6).

Tres cosas se fijan aquí:

1. REGRESIÓN DORADA DEL COMPILADOR. Los hashes son los MISMOS que congela
   test_lot_stop_nivel.py (capturados el 2026-09-15, antes del camino): una
   definición SIN `steps` tiene que compilar EXACTAMENTE igual después de la
   feature (regla nº1 del repo). Si esto falla, el camino tocó el path normal.
2. NORMALIZACIÓN. `normaliza_steps` valida la forma (≥2 pasos, ningún paso
   vacío, `same_bar` bool) y normaliza cada paso con la MISMA `_normalize_tree`
   de entrada/salida.
3. 422. Las combinaciones imposibles rebota al GUARDAR (field_validator de
   StrategyCreate) y revientan al COMPILAR (defense in depth: lo que llega al
   motor inválido es payload corrupto, no un camino a medias).
"""
import json

import pytest
from pydantic import ValidationError

from app.schemas.strategy import StrategyCreate
from app.services.strategy_engine import (
    compile_strategy_def, normaliza_steps, translate_strategy,
)

import numpy as np
import pandas as pd


# ── La definición representativa del dorado (misma que test_lot_stop_nivel) ──

SIEMPRE = {
    "type": "group", "operator": "AND",
    "conditions": [{
        "type": "indicator_comparison",
        "source": {"name": "Bar Close", "offset": 0},
        "comparator": "GREATER_THAN", "target": 0.0, "timeframe": "1m",
    }],
}

DEF_CON_PYR = {
    "bias": "short",
    "entry_logic": {"timeframe": "1m", "root_condition": SIEMPRE},
    "exit_logic": {"timeframe": "1m",
                   "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
    "risk_management": {
        "size_by_sl": False, "use_hard_stop": True,
        "hard_stop": {"type": "Percentage", "value": 2.0},
    },
    "pyramiding": {
        "timeframe": "1m", "mode": "individual",
        "levels": [
            {"times": 3, "root_condition": SIEMPRE, "action": "add",
             "unit": "pct", "capital_pct": 5},
            {"times": 1, "root_condition": SIEMPRE, "action": "add",
             "unit": "usd", "capital_pct": 500, "size_by_sl": True,
             "hybrid_stop": True, "hybrid_black_swan_pct": 50.0,
             "hybrid_max_loss_pct": 1.0},
            {"times": 2, "root_condition": SIEMPRE, "action": "reduce",
             "unit": "pct", "capital_pct": 25},
        ],
    },
}

# Congelados el 2026-09-15 ANTES del camino (ver test_lot_stop_nivel.py, que
# los capturó con el mismo escenario).
# En sailor (17-sep) el dorado es el de test_lot_stop_nivel: cada nivel lleva
# las claves de los grupos de piramide desde el 16-sep (`group`, `sequential`,
# `move`, `def_index`); verificado que es el MISMO hash que sailor daba antes
# de integrar el lot_stop y el camino.
GOLDEN_CON_PYR = "97cc54570067a9f67f00f6bf32232bec2ce944f871b37b29ea2860d7c0455047"

CAMINO_2P = [json.loads(json.dumps(SIEMPRE)), json.loads(json.dumps(SIEMPRE))]


def _hash_compilado(definicion: dict) -> str:
    import hashlib
    dump = json.dumps(compile_strategy_def(definicion), sort_keys=True, default=str)
    return hashlib.sha256(dump.encode()).hexdigest()


def _def_fresh() -> dict:
    # Copia profunda OBLIGATORIA: compile/normaliza mutan los nombres IN PLACE.
    return json.loads(json.dumps(DEF_CON_PYR))


# ── 1. Regresión dorada: sin steps, bit-identico ───────────────────────────

def test_dorado_definicion_con_piramidacion_sin_steps():
    """Mismo hash que antes del camino (regla nº1 del PRD)."""
    import hashlib
    dump = json.dumps(compile_strategy_def(_def_fresh()), sort_keys=True, default=str)
    assert hashlib.sha256(dump.encode()).hexdigest() == GOLDEN_CON_PYR


def test_nivel_normal_no_gana_claves_de_camino():
    """El dict compilado de un nivel SIN steps no lleva steps_def ni same_bar."""
    niveles = compile_strategy_def(_def_fresh())["pyramid_levels_def"]
    assert len(niveles) == 3
    for nv in niveles:
        assert "steps_def" not in nv and "same_bar" not in nv


# ── 2. Normalización ───────────────────────────────────────────────────────

def test_normaliza_camino_valido_con_default_same_bar():
    pasos = [
        {"type": "group", "operator": "AND", "conditions": [{
            "type": "indicator_comparison",
            "source": {"name": "Bar Close"}, "comparator": "GREATER_THAN",
            "target": 1.0}]},
        {"type": "group", "operator": "OR", "conditions": [{
            "type": "indicator_comparison",
            "source": {"name": "Volume"}, "comparator": "GREATER_THAN",
            "target": 100.0}]},
    ]
    out = normaliza_steps(pasos)
    assert out["same_bar"] is True          # default del PRD (Q1)
    # copia profunda normalizada: el input queda intacto (contrato del
    # validador pydantic, mismo que normaliza_lot_stop)
    assert out["steps"] is not pasos
    assert pasos[0]["conditions"][0]["source"]["name"] == "Bar Close"
    # la MISMA normalización de nombres que entrada/salida
    assert out["steps"][0]["conditions"][0]["source"]["name"] == "Close"


def test_normaliza_same_bar_false_se_conserva():
    out = normaliza_steps(CAMINO_2P, False)
    assert out["same_bar"] is False
    assert normaliza_steps(CAMINO_2P, None)["same_bar"] is True


@pytest.mark.parametrize("steps, same_bar", [
    ("primero A luego B", True),            # no es una lista
    ({0: "A", 1: "B"}, True),               # dict en vez de lista
    ([SIEMPRE], True),                      # un solo paso
    ([], True),                             # cero pasos
    ([SIEMPRE, {"type": "group", "operator": "AND", "conditions": []}], True),  # paso vacío
    ([SIEMPRE, {"operator": "AND"}], True), # paso sin conditions
    ([SIEMPRE, "que suba el VWAP"], True),  # paso que no es dict
    ([SIEMPRE, SIEMPRE], "si"),             # same_bar no bool
    ([SIEMPRE, SIEMPRE], 1),                # 1 de int tampoco: bool explícito
])
def test_normaliza_rechaza_imposibles(steps, same_bar):
    with pytest.raises(ValueError):
        normaliza_steps(steps, same_bar)


# ── 3. Compilador: steps_def + same_bar, resto del nivel igual ─────────────

def _nivel_camino(**kw):
    nv = {"times": 2, "steps": [json.loads(json.dumps(SIEMPRE)),
                                json.loads(json.dumps(SIEMPRE))],
          "action": "add", "unit": "pct", "capital_pct": 5, "same_bar": True}
    nv.update(kw)
    return nv


def test_compilador_guarda_steps_def_y_same_bar_sin_root_condition():
    d = _def_fresh()
    d["pyramiding"]["levels"][0] = _nivel_camino(same_bar=False)
    niveles = compile_strategy_def(d)["pyramid_levels_def"]
    assert "root_condition" not in niveles[0]
    # copia normalizada (misma _normalize_tree que root_condition)
    normalizado = json.loads(json.dumps(SIEMPRE))
    normalizado["conditions"][0]["source"]["name"] = "Close"
    assert niveles[0]["steps_def"] == [normalizado, normalizado]
    assert niveles[0]["same_bar"] is False
    # el resto del nivel se compila IGUAL que un nivel normal
    assert niveles[0]["action"] == "add"
    assert niveles[0]["unit"] == "pct"
    assert niveles[0]["capital_frac"] == 0.05
    assert niveles[0]["max_fires"] == 2
    assert niveles[0]["amount_usd"] == 0.0
    # los niveles normales de la misma definición quedan intactos
    assert "steps_def" not in niveles[1] and niveles[1]["root_condition"]


def test_compilador_camino_convive_con_lot_stop():
    d = _def_fresh()
    d["pyramiding"]["levels"][0] = _nivel_camino(
        lot_stop={"mode": "pct", "pct": 2.5})
    niveles = compile_strategy_def(d)["pyramid_levels_def"]
    assert niveles[0]["steps_def"] and niveles[0]["lot_stop"] == {"mode": "pct", "pct": 2.5}


def test_compilador_revienta_con_steps_y_root_condition():
    d = _def_fresh()
    d["pyramiding"]["levels"][0] = _nivel_camino()
    d["pyramiding"]["levels"][0]["root_condition"] = json.loads(json.dumps(SIEMPRE))
    with pytest.raises(ValueError, match="a la vez"):
        compile_strategy_def(d)


@pytest.mark.parametrize("steps", [
    [SIEMPRE],
    [SIEMPRE, {"type": "group", "operator": "AND", "conditions": []}],
])
def test_compilador_revienta_con_camino_invalido(steps):
    d = _def_fresh()
    d["pyramiding"]["levels"][0] = _nivel_camino()
    d["pyramiding"]["levels"][0]["steps"] = steps
    with pytest.raises(ValueError, match="steps"):
        compile_strategy_def(d)


def test_camino_has_special_fuerza_el_path_python():
    """Pirámide (con o sin camino) => has_special: el JIT nunca lo ve."""
    d = _def_fresh()
    d["pyramiding"]["levels"][0] = _nivel_camino()
    assert compile_strategy_def(d)["_indicator_plan"]["has_special"] is True


# ── 4. Evaluador: steps_signals, misma caché, máscara por paso ─────────────

def _frame(n=30):
    ts = pd.date_range("2026-09-16 04:00", periods=n, freq="1min")
    return pd.DataFrame({
        "timestamp": ts, "open": np.full(n, 1.0), "high": np.full(n, 1.01),
        "low": np.full(n, 0.99), "close": np.full(n, 1.0),
        "volume": np.full(n, 1000.0),
    })


def test_translate_emite_steps_signals_y_no_signals():
    d = _def_fresh()
    d["pyramiding"]["levels"][0] = _nivel_camino(same_bar=False)
    s = translate_strategy(_frame(), d, {}, compiled=compile_strategy_def(d))
    nivel = s["pyramid_levels"][0]
    assert "signals" not in nivel
    assert len(nivel["steps_signals"]) == 2
    assert all(isinstance(arr, np.ndarray) and arr.dtype == bool
               for arr in nivel["steps_signals"])
    assert nivel["same_bar"] is False
    # el resto de claves del nivel viaja igual que un nivel normal
    assert nivel["action"] == "add" and nivel["max_fires"] == 2


def test_translate_aplica_la_ventana_horaria_a_cada_paso():
    """§11-10 en la fuente: ningún paso engancha fuera de entry_time_windows."""
    d = _def_fresh()
    d["pyramiding"]["levels"][0] = _nivel_camino()
    d["entry_logic"]["entry_time_windows"] = [{"from_time": "04:00", "to_time": "04:10"}]
    frame = _frame()   # 04:00-04:29
    s = translate_strategy(frame, d, {}, compiled=compile_strategy_def(d))
    nivel = s["pyramid_levels"][0]
    minutos = pd.to_datetime(frame["timestamp"]).dt.hour * 60 + \
        pd.to_datetime(frame["timestamp"]).dt.minute
    mins = minutos.values
    for k, arr in enumerate(nivel["steps_signals"]):
        arr = np.asarray(arr, dtype=bool)
        fuera = arr & (mins > 4 * 60 + 10)
        assert not fuera.any(), f"el paso {k + 1} engancha fuera de ventana"
        assert (arr & (mins <= 4 * 60 + 10)).any(), f"el paso {k + 1} no engancha dentro"


# ── 5. Schema: 422 al guardar, dict opaco intacto ──────────────────────────

def _payload(pyramiding):
    return {
        "name": "t", "bias": "short",
        "entry_logic": {"timeframe": "1m",
                        "root_condition": json.loads(json.dumps(SIEMPRE))},
        "risk_management": {},
        "pyramiding": pyramiding,
    }


def test_schema_acepta_camino_valido_y_no_muta_el_bloque():
    pir = {"levels": [_nivel_camino()]}
    modelo = StrategyCreate(**_payload(pir))
    assert modelo.pyramiding == pir  # opaco: pasa tal cual


@pytest.mark.parametrize("steps", [
    [SIEMPRE],
    [],
    [SIEMPRE, {"type": "group", "operator": "AND", "conditions": []}],
    "no soy una lista",
])
def test_schema_rechaza_camino_invalido_con_422(steps):
    with pytest.raises(ValidationError, match="steps"):
        StrategyCreate(**_payload({"levels": [_nivel_camino(steps=steps)]}))


def test_schema_rechaza_same_bar_no_bool():
    nv = _nivel_camino()
    nv["same_bar"] = "si"
    with pytest.raises(ValidationError, match="same_bar"):
        StrategyCreate(**_payload({"levels": [nv]}))


def test_schema_rechaza_steps_y_root_condition_juntos():
    nv = _nivel_camino()
    nv["root_condition"] = json.loads(json.dumps(SIEMPRE))
    with pytest.raises(ValidationError, match="exclusivos"):
        StrategyCreate(**_payload({"levels": [nv]}))


def test_schema_camino_sin_root_condition_pasa():
    """§11 frontera: steps sin root_condition → 200."""
    modelo = StrategyCreate(**_payload({"levels": [_nivel_camino()]}))
    assert "root_condition" not in modelo.pyramiding["levels"][0]


def test_schema_sin_steps_pasa_sin_tocar_nada():
    modelo = StrategyCreate(**_payload(json.loads(json.dumps(DEF_CON_PYR["pyramiding"]))))
    assert modelo.pyramiding == DEF_CON_PYR["pyramiding"]
