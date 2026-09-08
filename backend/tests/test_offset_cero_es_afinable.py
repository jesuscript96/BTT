# -*- coding: utf-8 -*-
"""Un `offset` en 0 es un VALOR, no una opcion apagada.

`extract_parameters` tiene una regla general —"valor 0 = funcion desactivada,
no se ofrece"— que es correcta para un stop o un take profit, pero NO para el
offset de un indicador: offset 0 significa "esta misma vela", que es una
configuracion normal y perfectamente optimizable.

Lo destapo Jaume el 7-sep-2026: su estrategia tiene «Bar Close < Prev. Bar Low»
(el objetivo con offset 0) y «Low Bar > VWAP» (la fuente con offset 1). En el
genetico solo aparecia la segunda, y no habia forma de saber por que. Sin este
test, cualquiera puede "limpiar" el allow_zero y volver a esconder el gen sin
que salte nada — es el mismo fallo que tuvo el margen del stop de estructura.

Los tres motores beben de aqui: el optimizador 3D, el Walk Forward y el genetico.
"""
import pytest

from app.services.optimization_service import extract_parameters


def _condicion(source, comparator, target):
    return {"type": "indicator_comparison", "source": source,
            "comparator": comparator, "target": target, "timeframe": "1m"}


def _estrategia(conditions):
    return {
        "name": "prueba", "bias": "short",
        "entry_logic": {"timeframe": "1m", "root_condition": {
            "type": "group", "operator": "AND", "conditions": conditions}},
        "risk_management": {},
    }


def _ids(defn):
    return {p["id"]: p for p in extract_parameters(defn)}


class TestOffsetCero:
    def test_el_offset_del_OBJETIVO_en_cero_se_ofrece(self):
        """El caso de Jaume: «Bar Close < Prev. Bar Low», objetivo con offset 0."""
        d = _estrategia([_condicion(
            {"name": "Bar Close", "offset": 0}, "LESS_THAN",
            {"name": "Prev. Bar Low", "offset": 0})])
        g = _ids(d)
        clave = "entry_logic.root_condition.conditions.0.target.offset"
        assert clave in g, "el offset del objetivo en 0 no se ofrece"
        assert g[clave]["current_value"] == 0

    def test_el_rango_propuesto_llega_a_diez_velas_atras(self):
        d = _estrategia([_condicion(
            {"name": "Bar Close", "offset": 0}, "LESS_THAN",
            {"name": "Prev. Bar Low", "offset": 0})])
        p = _ids(d)["entry_logic.root_condition.conditions.0.target.offset"]
        assert p["min"] == 0 and p["max"] >= 10, (p["min"], p["max"])

    def test_el_offset_de_la_FUENTE_en_cero_tambien(self):
        d = _estrategia([_condicion(
            {"name": "Low Bar", "offset": 0}, "GREATER_THAN",
            {"name": "VWAP", "offset": 0})])
        g = _ids(d)
        assert "entry_logic.root_condition.conditions.0.source.offset" in g
        assert "entry_logic.root_condition.conditions.0.target.offset" in g

    def test_un_offset_distinto_de_cero_sigue_saliendo(self):
        """No se rompe lo que ya funcionaba."""
        d = _estrategia([_condicion(
            {"name": "Low Bar", "offset": 1}, "GREATER_THAN",
            {"name": "VWAP", "offset": 0})])
        p = _ids(d)["entry_logic.root_condition.conditions.0.source.offset"]
        assert p["current_value"] == 1


class TestLosDemasEnterosNoCambian:
    """La regla del 0 sigue en pie para todo lo que no sea `offset`: un periodo
    o un contador en 0 no significan nada y no deben ofrecerse."""

    @pytest.mark.parametrize("clave", ["period", "consecutive_count", "days_lookback"])
    def test_un_entero_en_cero_que_no_es_offset_se_sigue_descartando(self, clave):
        d = _estrategia([_condicion(
            {"name": "SMA", "offset": 0, clave: 0}, "GREATER_THAN", 5.0)])
        g = _ids(d)
        assert f"entry_logic.root_condition.conditions.0.source.{clave}" not in g
        # pero el offset del mismo indicador si
        assert "entry_logic.root_condition.conditions.0.source.offset" in g

    def test_un_entero_distinto_de_cero_sigue_saliendo(self):
        d = _estrategia([_condicion(
            {"name": "SMA", "offset": 0, "period": 20}, "GREATER_THAN", 5.0)])
        assert "entry_logic.root_condition.conditions.0.source.period" in _ids(d)
