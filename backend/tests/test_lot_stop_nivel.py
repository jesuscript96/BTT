"""SL POR LOTE en piramidación — P0: schema + compilador (PRD 2026-09-15, §6.4).

Tres cosas se fijan aquí:

1. REGRESIÓN DORADA DEL COMPILADOR. Los hashes están congelados del código
   ANTES del cambio (capturados el 2026-09-15 con compile_strategy_def tal
   cual estaba): una definición sin `lot_stop` tiene que compilar EXACTAMENTE
   igual después de la feature (regla nº1 del repo, PRD §4). Si este test
   falla, la feature ha tocado el camino sin lot_stop.
2. NORMALIZACIÓN. Los nombres del vocabulario estructural (los del SL del
   trade) se resuelven a las claves canónicas {last_pivot, previous_max,
   hod, lod} y los números se coercen.
3. 422. Las combinaciones imposibles rebota al GUARDAR (field_validator de
   StrategyCreate) y revientan al COMPILAR (defense in depth: lo que llega
   al motor inválido es payload corrupto, no un cinturón fantasma).
"""
import hashlib
import json

import pytest
from pydantic import ValidationError

from app.schemas.strategy import StrategyCreate
from app.services.strategy_engine import (
    compile_strategy_def, normaliza_lot_stop, translate_strategy,
)

import numpy as np
import pandas as pd


# ── La definición representativa del dorado (misma que la captura pre-cambio) ──

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
DEF_SIN_PYR = {k: v for k, v in DEF_CON_PYR.items() if k != "pyramiding"}

# Congelados el 2026-09-15 ANTES de tocar strategy_engine (script de captura
# en .tmp_lot_stop/captura_golden.py del scratchpad de la sesión).
GOLDEN_CON_PYR = "3c2474e661a9ce09de26e97595f19969cbc1dcc04ff144744eb56a1d9d2ddb4a"
GOLDEN_SIN_PYR = "8630d492c467310e09cefb963201904fe8bc65270d3f9114ceb7b40a4aadfe86"


def _hash_compilado(definicion: dict) -> str:
    dump = json.dumps(compile_strategy_def(definicion), sort_keys=True, default=str)
    return hashlib.sha256(dump.encode()).hexdigest()


def _def_fresh() -> dict:
    """Copia profunda de la definición del dorado.

    OBLIGATORIO: `compile`/`translate` normalizan los nombres de indicadores
    IN PLACE ("Bar Close" → "Close"), así que compartir el dict entre tests
    contamina el enum del schema (que no admite "Close") y puede desordenar
    el dorado si cambia el orden de ejecución.
    """
    return json.loads(json.dumps(DEF_CON_PYR))


# ── 1. Regresión dorada ────────────────────────────────────────────────────

def test_dorado_definicion_con_piramidacion_sin_lot_stop():
    assert _hash_compilado(_def_fresh()) == GOLDEN_CON_PYR


def test_dorado_definicion_sin_piramidacion():
    assert _hash_compilado(json.loads(json.dumps(DEF_SIN_PYR))) == GOLDEN_SIN_PYR


def test_nivel_sin_lot_stop_no_lleva_la_clave():
    """El dict compilado del nivel no gana 'lot_stop': solo el que la declara."""
    niveles = compile_strategy_def(_def_fresh())["pyramid_levels_def"]
    assert len(niveles) == 3
    for nv in niveles:
        assert "lot_stop" not in nv


# ── 2. Normalización ───────────────────────────────────────────────────────

def test_normaliza_pct_basico_y_coerciones():
    assert normaliza_lot_stop({"mode": "pct", "pct": 2.5}) == {"mode": "pct", "pct": 2.5}
    # str numérico (la UI manda strings) y mode en mayúsculas
    assert normaliza_lot_stop({"mode": "PCT", "pct": "1.5"}) == {"mode": "pct", "pct": 1.5}
    # entero → float
    assert normaliza_lot_stop({"mode": "pct", "pct": 3}) == {"mode": "pct", "pct": 3.0}


def test_normaliza_structure_pivote_con_swing_ventana_offset():
    out = normaliza_lot_stop({
        "mode": "structure", "level": "Último pivote", "swing": "up",
        "pivot_window": "5", "offset_pct": 0.5,
    })
    assert out == {"mode": "structure", "level": "last_pivot", "swing": "up",
                   "pivot_window": 5, "offset_pct": 0.5}


def test_normaliza_defaults_del_pivote():
    out = normaliza_lot_stop({"mode": "structure", "level": "last_pivot", "swing": "down"})
    assert out == {"mode": "structure", "level": "last_pivot", "swing": "down",
                   "pivot_window": 3, "offset_pct": 0.0}


def test_normaliza_alias_pivot_high_lleva_swing_implicito():
    """'Pivot High' (vocabulario del SL del trade) = last_pivot + swing up."""
    out = normaliza_lot_stop({"mode": "structure", "level": "Pivot High"})
    assert out["level"] == "last_pivot" and out["swing"] == "up"
    out = normaliza_lot_stop({"mode": "structure", "level": "último pivote bajo"})
    assert out["level"] == "last_pivot" and out["swing"] == "down"


def test_normaliza_previous_max_hod_lod_sin_claves_inertes():
    out = normaliza_lot_stop({"mode": "structure", "level": "Previous max",
                              "swing": "up", "pivot_window": 7})
    # swing/pivot_window no aplican fuera del pivote: no viajan
    assert out == {"mode": "structure", "level": "previous_max", "offset_pct": 0.0}
    assert normaliza_lot_stop({"mode": "Structure", "level": "High of Day"}) == {
        "mode": "structure", "level": "hod", "offset_pct": 0.0}
    assert normaliza_lot_stop({"mode": "structure", "level": "LOD"}) == {
        "mode": "structure", "level": "lod", "offset_pct": 0.0}


def test_normaliza_offset_sobre_hod():
    out = normaliza_lot_stop({"mode": "structure", "level": "hod", "offset_pct": "0.25"})
    assert out == {"mode": "structure", "level": "hod", "offset_pct": 0.25}


# ── 3. Combinaciones imposibles ────────────────────────────────────────────

@pytest.mark.parametrize("bloque, motivo", [
    ({"mode": "atr"}, "mode fuera de vocabulario"),
    ({}, "sin mode"),
    ({"mode": "pct"}, "pct sin número"),
    ({"mode": "pct", "pct": 0}, "pct en cero"),
    ({"mode": "pct", "pct": -2}, "pct negativo"),
    ({"mode": "pct", "pct": True}, "bool no es un pct"),
    ({"mode": "pct", "pct": "alto"}, "string no numérico"),
    ({"mode": "structure"}, "structure sin level"),
    ({"mode": "structure", "level": "VWAP"}, "level fuera de vocabulario"),
    ({"mode": "structure", "level": "last_pivot"}, "pivote sin swing"),
    ({"mode": "structure", "level": "last_pivot", "swing": "lateral"}, "swing basura"),
    ({"mode": "structure", "level": "last_pivot", "swing": "up", "pivot_window": 0},
     "ventana en cero"),
    ({"mode": "structure", "level": "hod", "offset_pct": -0.5}, "offset negativo"),
    ("2%", "no es un dict"),
])
def test_normaliza_rechaza_imposibles(bloque, motivo):
    with pytest.raises(ValueError):
        normaliza_lot_stop(bloque)


# ── 4. Compilador: valida fuerte y solo en niveles add ─────────────────────

def _nivel_add(lot_stop):
    return {"times": 2, "root_condition": json.loads(json.dumps(SIEMPRE)),
            "action": "add", "unit": "pct", "capital_pct": 5, "lot_stop": lot_stop}


def test_compilador_adjunta_lot_stop_canonico_solo_al_nivel_que_lo_declara():
    d = json.loads(json.dumps(DEF_CON_PYR))  # copia profunda
    d["pyramiding"]["levels"][0]["lot_stop"] = {
        "mode": "structure", "level": "Último pivote", "swing": "up",
        "pivot_window": 3, "offset_pct": 0.5}
    niveles = compile_strategy_def(d)["pyramid_levels_def"]
    assert niveles[0]["lot_stop"] == {
        "mode": "structure", "level": "last_pivot", "swing": "up",
        "pivot_window": 3, "offset_pct": 0.5}
    assert "lot_stop" not in niveles[1]
    assert "lot_stop" not in niveles[2]


def test_compilador_revienta_con_lot_stop_invalido():
    d = json.loads(json.dumps(DEF_CON_PYR))
    d["pyramiding"]["levels"][0]["lot_stop"] = {"mode": "pct"}
    with pytest.raises(ValueError, match="lot_stop"):
        compile_strategy_def(d)


def test_compilador_rechaza_lot_stop_en_reduce():
    d = json.loads(json.dumps(DEF_CON_PYR))
    d["pyramiding"]["levels"][2]["lot_stop"] = {"mode": "pct", "pct": 2}
    with pytest.raises(ValueError, match="action='add'"):
        compile_strategy_def(d)


def test_translate_pasa_lot_stop_al_simulador_solo_si_existe():
    """La lista que consume simulate lleva la clave solo en el nivel que la declara."""
    d = json.loads(json.dumps(DEF_CON_PYR))
    d["pyramiding"]["levels"][0]["lot_stop"] = {"mode": "pct", "pct": 2.5}
    frame = pd.DataFrame({
        "timestamp": pd.date_range("2026-09-15 04:00", periods=30, freq="1min"),
        "open": np.full(30, 1.0), "high": np.full(30, 1.01),
        "low": np.full(30, 0.99), "close": np.full(30, 1.0),
        "volume": np.full(30, 1000.0),
    })
    s = translate_strategy(frame, d, {}, compiled=compile_strategy_def(d))
    niveles = s["pyramid_levels"]
    assert niveles[0]["lot_stop"] == {"mode": "pct", "pct": 2.5}
    assert "lot_stop" not in niveles[1]
    assert "lot_stop" not in niveles[2]


# ── 5. Schema: 422 al guardar, dict opaco intacto ──────────────────────────

def _payload(pyramiding):
    return {
        "name": "t", "bias": "short",
        "entry_logic": {"timeframe": "1m",
                        "root_condition": json.loads(json.dumps(SIEMPRE))},
        "risk_management": {},
        "pyramiding": pyramiding,
    }


def test_schema_acepta_lot_stop_valido_y_no_muta_el_bloque():
    pir = {"levels": [_nivel_add({"mode": "pct", "pct": 2.5})]}
    modelo = StrategyCreate(**_payload(pir))
    assert modelo.pyramiding == pir  # opaco: pasa tal cual


@pytest.mark.parametrize("lot_stop", [
    {"mode": "pct"},
    {"mode": "pct", "pct": 0},
    {"mode": "structure", "level": "VWAP"},
    {"mode": "structure", "level": "last_pivot"},
    {"mode": "telepatico", "pct": 1},
])
def test_schema_rechaza_lot_stop_invalido_con_422(lot_stop):
    with pytest.raises(ValidationError, match="lot_stop"):
        StrategyCreate(**_payload({"levels": [_nivel_add(lot_stop)]}))


def test_schema_rechaza_lot_stop_en_nivel_reduce():
    pir = {"levels": [_nivel_add({"mode": "pct", "pct": 2}), {
        "times": 1, "root_condition": SIEMPRE, "action": "reduce",
        "unit": "pct", "capital_pct": 25, "lot_stop": {"mode": "pct", "pct": 2}}]}
    with pytest.raises(ValidationError, match="action='add'"):
        StrategyCreate(**_payload(pir))


def test_schema_sin_lot_stop_pasa_sin_tocar_nada():
    modelo = StrategyCreate(**_payload(json.loads(json.dumps(DEF_CON_PYR["pyramiding"]))))
    assert modelo.pyramiding == DEF_CON_PYR["pyramiding"]
