"""Prealerta POR DISTANCIA con el precio en vivo (29-sep-2026).

Jaume: «cuando una de las condiciones esté a X % de distancia de cumplirse, que
prealerte… con el precio en vivo, a un 2-3 %, lo mismo para la entrada y para
el añadido». Cada segundo, con la vela EN CURSO que montan los agregados `A.`
(ningún socket nuevo): las condiciones que no son de precio tienen que
cumplirse; de las de precio falta como mucho una, a menos del X %.
"""
import os
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services.bot_alerts_engine import _EstadoPar
from app.services.bot_alerts_prealerta_simple import PrealertaDistancia, distancia_pct, etiqueta
from app.services.bot_alerts_telegram import formatear

TK = "AAA"
BASE = pd.Timestamp("2026-09-29 08:00:00")


def _cond(op, valor, fuente="Bar Close"):
    return {"type": "indicator_comparison", "source": {"name": fuente, "offset": 0},
            "comparator": op, "target": valor, "timeframe": "1m"}


SI = _cond("GREATER_THAN", 1.0)            # el precio (2.0) ya es > 1


def _velas(n=30):
    return [{"timestamp": str(BASE + pd.Timedelta(minutes=i)), "open": 2.0, "high": 2.05,
             "low": 1.95, "close": 2.0, "volume": 10000.0} for i in range(n)]


def _en_curso(close, n=30):
    """La vela que se está formando: su cierre es el precio en vivo."""
    return {"timestamp": BASE + pd.Timedelta(minutes=n), "open": 2.0,
            "high": max(2.0, close), "low": min(2.0, close), "close": close, "volume": 500.0}


def _estrategia(entrada, niveles=()):
    sdef = {"direction": "shortonly",
            "entry_logic": {"timeframe": "1m", "root_condition": {
                "type": "group", "operator": "AND", "conditions": list(entrada)}},
            "pyramiding": {"timeframe": "1m", "levels": [
                {"times": 1, "action": "add", "root_condition": {
                    "type": "group", "operator": "AND", "conditions": list(c)}} for c in niveles]}}
    return {"strategy_id": "id-A", "name": "Estrategia A", "definition": sdef,
            "compiled": {}, "riesgo_usd": 100.0}


def _runner(est, dentro=False):
    motor = SimpleNamespace(estrategias=[est], _estado={})
    if dentro:
        e = _EstadoPar()
        e.entradas_avisadas.add(10)
        e.idx_ultima_entrada_avisada = 10
        motor._estado[(TK, est["strategy_id"])] = e
    return SimpleNamespace(_velas={TK: _velas()}, _stats={TK: {"prev_close": 1.0}}, motor=motor)


def _vivo(est, precio, dentro=False, umbral=2.0):
    return PrealertaDistancia(umbral_pct=umbral).evaluar_vivo(_runner(est, dentro), TK, _en_curso(precio))


# ── la regla ──────────────────────────────────────────────────────────────
def test_la_de_precio_que_falta_a_menos_del_umbral_prealerta_con_la_distancia():
    # Short: «Close < 1,97» con el precio en vivo a 2,00 → le falta un 1,5 %.
    evs = _vivo(_estrategia([SI, _cond("LESS_THAN", 1.97)]), 2.0)
    assert [e.tipo for e in evs] == ["entrada"]
    assert evs[0].motivo == "Falta: Bar Close < 1.97 — a 1.5 %"
    assert evs[0].precio == 2.0


def test_mas_lejos_que_el_umbral_no_prealerta():
    assert _vivo(_estrategia([SI, _cond("LESS_THAN", 1.90)]), 2.0) == []      # 5,3 %
    assert len(_vivo(_estrategia([SI, _cond("LESS_THAN", 1.90)]), 2.0, umbral=6)) == 1


def test_el_precio_en_vivo_manda_no_el_cierre_de_la_vela_anterior():
    """Las velas cerradas cierran a 2,00 (a un 5,3 % de 1,90): en vivo baja a 1,93."""
    evs = _vivo(_estrategia([SI, _cond("LESS_THAN", 1.90)]), 1.93)
    assert len(evs) == 1 and "a 1.6 %" in evs[0].motivo


def test_si_ya_se_cumplen_todas_avisa_que_se_cumple_ahora():
    evs = _vivo(_estrategia([SI, _cond("LESS_THAN", 2.5)]), 2.0)
    assert evs[0].motivo.startswith("Se cumple ahora")


def test_una_que_no_es_de_precio_tiene_que_estar_cumplida():
    """El volumen (o el tiempo, un patrón…) no tiene distancia en %: si falta, nada."""
    no_precio = _cond("GREATER_THAN", 1e12, fuente="Volume")
    assert _vivo(_estrategia([SI, no_precio]), 2.0) == []


def test_si_faltan_dos_no_prealerta_aunque_esten_cerca():
    assert _vivo(_estrategia([_cond("LESS_THAN", 1.99), _cond("LESS_THAN", 1.98)]), 2.0) == []


def test_con_posicion_mide_el_anyadido_y_no_la_entrada():
    est = _estrategia([SI, _cond("LESS_THAN", 1.97)], niveles=[[SI, _cond("GREATER_THAN", 2.03)]])
    evs = _vivo(est, 2.0, dentro=True)
    assert [(e.tipo, e.nivel) for e in evs] == [("piramide", 1)]
    assert "a 1.5 %" in evs[0].motivo


def test_distancia_a_un_nivel_con_margen_por_debajo():
    """«Close a menos del 10 % bajo VWAP»: por encima del VWAP le falta bajar hasta él."""
    cond = {"type": "price_level_distance", "source": {"name": "Bar Close", "offset": 0},
            "level": {"name": "VWAP", "offset": 0}, "comparator": "DISTANCE_LT",
            "value_pct": 10, "timeframe": "1m", "position": "below"}
    velas = pd.DataFrame(_velas() + [_en_curso(2.5)])
    from app.services.market_frame import build_market_frame
    velas["timestamp"] = pd.to_datetime(velas["timestamp"])
    frame = build_market_frame(velas, TK, {"prev_close": 1.0})
    vwap = float(frame["vwap"].iloc[-1])
    d = distancia_pct(cond, frame, "1m", {"prev_close": 1.0}, {})
    assert d == pytest.approx((2.5 - vwap) / vwap * 100, rel=1e-3)


# ── el texto ──────────────────────────────────────────────────────────────
def test_etiquetas_legibles():
    """29-sep: salían «Close DISTANCE_LT None» y «Close > EMA» sin el periodo."""
    assert etiqueta({"type": "price_level_distance", "source": {"name": "Bar Close"},
                     "level": {"name": "VWAP"}, "comparator": "DISTANCE_LT",
                     "value_pct": 10, "position": "below"}) == "Bar Close a <10 % bajo VWAP"
    assert etiqueta(_cond("GREATER_THAN", {"name": "EMA", "period": 10})) == "Bar Close > EMA(10)"


def test_telegram_de_se_cumple_ahora():
    e = _vivo(_estrategia([SI, _cond("LESS_THAN", 2.5)]), 2.0)[0]
    texto = formatear(e)
    assert "PREALERTA" in texto and "Se cumple ahora" in texto and "Acciones" not in texto


# ── dentro del proceso: sin socket, con los agregados que ya le llegan ───
def _agregado(segundo, precio, n=30):
    t = (BASE + pd.Timedelta(minutes=n, seconds=segundo)).tz_localize("America/New_York")
    ms = int(t.timestamp() * 1000)
    return {"ev": "A", "sym": TK, "o": 2.0, "h": max(2.0, precio), "l": min(2.0, precio),
            "c": precio, "v": 100, "av": 300000 + segundo * 100, "s": ms, "e": ms + 1000}


@pytest.mark.timeout(120)
def test_el_proceso_prealerta_con_los_agregados_en_modo_distancia(monkeypatch):
    from app.services import bot_alerts_prealerta_proceso as pp
    monkeypatch.setenv("BOT_PREALERTA_MODO", "distancia")
    monkeypatch.setenv("BOT_PREALERTA_DISTANCIA_PCT", "2")
    recibidas = []
    p = pp.PrealertaEnProceso(al_prealerta=lambda evs, *a: recibidas.extend(evs))
    p.arrancar()
    try:
        est = _estrategia([SI, _cond("LESS_THAN", 1.97)])
        p.configurar([{**est, "activa": True}])
        p.hidratar(TK, _velas(), {"prev_close": 1.0})
        p.tickers([TK])
        time.sleep(2)
        p.tick(_agregado(5, 2.10))          # a un 6,6 %: nada
        p.tick(_agregado(6, 2.00))          # a un 1,5 %: prealerta
        fin = time.time() + 30
        while time.time() < fin and not recibidas:
            time.sleep(0.2)
        assert recibidas, "el proceso no prealertó con el precio en vivo"
        assert "a 1.5 %" in recibidas[0].motivo
    finally:
        p.parar()
