# -*- coding: utf-8 -*-
"""Las guardas NO pueden DESPLAZAR los indices de las condiciones antes de que
se escriban los genes.

OJO AL NOMBRE: va de desplazar posiciones, NO de quitar guardas. Las guardas
se siguen metiendo igual y siguen aplicandose; lo unico que cambia es el ORDEN
(primero los genes, luego las guardas).

EL FALLO (7-sep-2026, cazado con la corrida de Jaume):
`a_definicion` metia las guardas al PRINCIPIO del grupo raiz y despues escribia
los genes. Pero las rutas de los genes son POSICIONALES
(`...conditions.4.source.offset`) y salen de `extract_parameters` sobre la
estrategia SIN guardas. Con 4 guardas, cada gen caia 4 posiciones mas alla.

En su corrida, el gen «PM High Gap (%) Target Value = 50» acababa escribiendo en
la primera guarda y la dejaba en `Bar Close > 50`. Sus acciones valen 1-7 $, asi
que la estrategia pasaba de 1.721 operaciones a 21; toda la poblacion se quedaba
por debajo del min_trades y la corrida entera daba fitness 0. Sin excepcion, sin
log y sin nada raro en la pantalla.

Es un fallo de los que no dan error, y sin este test vuelve solo en cuanto
alguien reordene la funcion.
"""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from genetico import afinar          # noqa: E402


GUARDAS = [
    {"type": "indicator_comparison", "source": {"name": "Bar Close", "offset": 0},
     "comparator": "GREATER_THAN", "target": 0.7, "timeframe": "1m"},
    {"type": "indicator_comparison", "source": {"name": "Dollar Volume", "offset": 0},
     "comparator": "GREATER_THAN", "target": 100000, "timeframe": "1m"},
]


def _cond(nombre, comparador, objetivo, offset=0):
    return {"type": "indicator_comparison",
            "source": {"name": nombre, "offset": offset},
            "comparator": comparador, "target": objetivo, "timeframe": "1m"}


def _config(guardas, operador="AND"):
    base = {
        "name": "base", "bias": "short",
        "entry_logic": {"timeframe": "1m", "root_condition": {
            "type": "group", "operator": operador, "conditions": [
                _cond("PM High Gap (%)", "GREATER_THAN", 50.0),
                _cond("Bar Close", "GREATER_THAN", 0.7),
                _cond("Low Bar", "GREATER_THAN", {"name": "VWAP", "offset": 0}, offset=1),
            ]}},
        "risk_management": {},
    }
    return {
        "modo": "mejorar", "estrategia_base": base, "guardas": guardas,
        "genes": [
            {"id": "g_gap", "label": "Entry PM High Gap (%) Target Value",
             "path": "entry_logic.root_condition.conditions.0.target",
             "current_value": 50.0, "min": 20, "max": 500, "step": 1},
            {"id": "g_off", "label": "Entry Low Bar offset",
             "path": "entry_logic.root_condition.conditions.2.source.offset",
             "current_value": 1, "min": 1, "max": 15, "step": 1},
        ],
    }


def _entradas(defn):
    return defn["entry_logic"]["root_condition"]["conditions"]


class TestConGuardas:
    def test_el_gen_escribe_en_SU_condicion_no_en_la_guarda(self):
        cfg = _config(GUARDAS)
        ind = {"valores": {"g_gap": 120.0, "g_off": 4}}
        cs = _entradas(afinar.a_definicion(ind, cfg))

        # Las 2 guardas van delante y quedan INTACTAS.
        assert cs[0]["source"]["name"] == "Bar Close" and cs[0]["target"] == 0.7, \
            "el gen del gap ha aterrizado sobre la guarda"
        assert cs[1]["source"]["name"] == "Dollar Volume" and cs[1]["target"] == 100000

        # Y los genes han caido donde tocaba.
        assert cs[2]["source"]["name"] == "PM High Gap (%)" and cs[2]["target"] == 120.0
        assert cs[4]["source"]["name"] == "Low Bar" and cs[4]["source"]["offset"] == 4

    def test_sin_tocar_los_genes_la_semilla_queda_igual(self):
        cfg = _config(GUARDAS)
        cs = _entradas(afinar.a_definicion(afinar.desde_semilla(cfg), cfg))
        assert cs[0]["target"] == 0.7           # guarda
        assert cs[2]["target"] == 50.0          # el gap original
        assert cs[4]["source"]["offset"] == 1   # el offset original

    def test_las_guardas_siguen_estando_y_delante(self):
        cfg = _config(GUARDAS)
        cs = _entradas(afinar.a_definicion({"valores": {"g_gap": 80.0}}, cfg))
        assert [c["source"]["name"] for c in cs[:2]] == ["Bar Close", "Dollar Volume"]
        assert len(cs) == 5


class TestSinGuardas:
    def test_sin_guardas_todo_igual_que_siempre(self):
        cfg = _config([])
        cs = _entradas(afinar.a_definicion({"valores": {"g_gap": 99.0, "g_off": 7}}, cfg))
        assert len(cs) == 3
        assert cs[0]["target"] == 99.0
        assert cs[2]["source"]["offset"] == 7


class TestRaizOR:
    """Con un OR la guarda no puede meterse dentro: se envuelve. Ahi los indices
    del grupo original NO se corren, pero el envoltorio cambia la raiz, asi que
    los genes tienen que aplicarse igualmente antes."""

    def test_con_raiz_OR_los_genes_tambien_llegan(self):
        cfg = _config(GUARDAS, operador="OR")
        d = afinar.a_definicion({"valores": {"g_gap": 77.0, "g_off": 3}}, cfg)
        raiz = d["entry_logic"]["root_condition"]
        assert raiz["operator"] == "AND"           # envuelto
        interior = raiz["conditions"][-1]
        assert interior["operator"] == "OR"
        assert interior["conditions"][0]["target"] == 77.0
        assert interior["conditions"][2]["source"]["offset"] == 3
