"""Velas propias a partir de operaciones sueltas (21-sep-2026).

La vela oficial de minuto llega ~2 s despues de cerrar el minuto; con las
operaciones (`T.`) el bot monta la suya y avisa a los :00,8. Lo que hay que
garantizar:
  1. Los odd lots (condicion 37) y demas condiciones sin precio cuentan en el
     volumen pero no mueven open/high/low/close (es lo que hace la oficial).
  2. Una vela que empezo a verse a mitad de minuto NO es completa.
  3. `velas_por_cerrar` entrega la vela solo cuando el minuto acabo hace >= el
     margen, y una sola vez.
  4. La prealerta por operacion mira el segundo REAL (44), y el `av` oficial
     sigue anclando el volumen.
  5. El runner sustituye la vela propia por la oficial sin anyadir otra.
"""
import numpy as np
import pandas as pd

from app.services import bot_alerts_prealertas as pre
from app.services import bot_alerts_runner as run_mod

BASE = int(pd.Timestamp("2026-09-21 04:05", tz="America/New_York").timestamp()) * 1000   # inicio del minuto, ms


def _op(seg, precio, tam=100, cond=None, ms_extra=0):
    return {"ev": "T", "sym": "KXIN", "p": precio, "s": tam, "t": BASE + seg * 1000 + ms_extra, "c": cond or []}


def test_odd_lots_cuentan_volumen_pero_no_precio():
    c = pre.ConstructorParcial()
    c.aplicar_operacion(_op(0, 2.00))
    c.aplicar_operacion(_op(5, 2.50, tam=50, cond=[37]))     # odd lot: no mueve el precio
    c.aplicar_operacion(_op(10, 1.90, tam=30, cond=[12, 37]))
    c.aplicar_operacion(_op(20, 2.10))
    v = c._curso["KXIN"]
    assert (v.open, v.high, v.low, v.close) == (2.00, 2.10, 2.00, 2.10)
    assert v.volumen == 280


def test_si_solo_hubo_odd_lots_el_precio_arranca_en_la_primera_normal():
    c = pre.ConstructorParcial()
    c.aplicar_operacion(_op(0, 9.99, tam=10, cond=[37]))
    c.aplicar_operacion(_op(3, 2.00))
    v = c._curso["KXIN"]
    assert (v.open, v.high, v.low, v.close) == (2.0, 2.0, 2.0, 2.0) and v.volumen == 110


def test_vela_vista_a_mitad_de_minuto_no_es_completa():
    c = pre.ConstructorParcial()
    c.aplicar_operacion(_op(30, 2.00))            # primera operacion en el segundo 30: llegamos tarde
    assert c._curso["KXIN"].completa is False
    # el minuto siguiente si esta completo aunque su primera operacion sea tardia
    c.aplicar_operacion({**_op(5, 2.05), "t": BASE + 60000 + 45000})
    assert c._curso["KXIN"].completa is True


def test_velas_por_cerrar_una_vez_y_con_margen():
    c = pre.ConstructorParcial()
    c.aplicar_operacion(_op(0, 2.00))
    c.aplicar_operacion(_op(59, 2.20))
    fin = (BASE + 60000) / 1000
    assert c.velas_por_cerrar(fin + 0.5) == [], "aun no ha pasado el margen"
    cerradas = c.velas_por_cerrar(fin + 0.9)
    assert [tk for tk, _ in cerradas] == ["KXIN"]
    vela = cerradas[0][1].como_vela_cerrada()
    assert str(vela["timestamp"]) == "2026-09-21 04:05:00" and vela["close"] == 2.20
    assert c.velas_por_cerrar(fin + 5) == [], "no se entrega dos veces"


def test_primera_operacion_del_minuto_siguiente_deja_la_anterior_terminada():
    c = pre.ConstructorParcial()
    c.aplicar_operacion(_op(10, 2.00))
    c.aplicar_operacion({**_op(0, 2.30), "t": BASE + 60000 + 300})   # 04:06:00,3
    fin = (BASE + 60000) / 1000
    cerradas = c.velas_por_cerrar(fin + 0.9)
    assert [(tk, v.minuto) for tk, v in cerradas] == [("KXIN", BASE // 1000)]
    assert c._curso["KXIN"].minuto == BASE // 1000 + 60


def test_prealerta_por_operacion_mira_el_segundo_real_y_av_ancla_el_volumen():
    c = pre.ConstructorParcial()
    c.aplicar_operacion(_op(10, 2.00, tam=1000))
    # llega el agregado oficial del segundo 10 (3 s tarde): av del dia 50.000, v 1.000
    c.aplicar({"ev": "A", "sym": "KXIN", "s": BASE + 10000, "o": 2.0, "h": 2.0, "l": 2.0, "c": 2.0, "v": 1000, "av": 50000})
    r = c.aplicar_operacion(_op(44, 1.95, tam=500, ms_extra=120))
    assert r is not None, "en el segundo 44 toca mirar"
    tk, v, ts_min, segundo = r
    assert segundo == 44 and v.close == 1.95
    # volumen: lo oficial hasta el segundo 10 (1.000) + la operacion posterior (500)
    assert v.volumen == 1500
    assert c.aplicar_operacion(_op(43, 1.96)) is None, "antes del 44 no se mira"


def test_runner_sustituye_la_vela_propia_por_la_oficial_sin_anyadir():
    r = run_mod.RunnerAlertas([], al_avisar=None)
    r._velas["KXIN"] = [{"timestamp": pd.Timestamp("2026-09-21 04:04"), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
                        {"timestamp": pd.Timestamp("2026-09-21 04:05"), "open": 2.0, "high": 2.2, "low": 2.0, "close": 2.2, "volume": 280}]
    assert r.tiene_vela("KXIN", pd.Timestamp("2026-09-21 04:05")) is True
    assert r.tiene_vela("KXIN", pd.Timestamp("2026-09-21 04:06")) is False
    ok = r.sustituir_vela("KXIN", {"timestamp": pd.Timestamp("2026-09-21 04:05"), "open": 2.0, "high": 2.25, "low": 2.0, "close": 2.21, "volume": 300})
    assert ok and len(r._velas["KXIN"]) == 2 and r._velas["KXIN"][-1]["close"] == 2.21
    assert r.sustituir_vela("KXIN", {"timestamp": pd.Timestamp("2026-09-21 04:07"), "close": 1}) is False


def test_los_prints_tardios_se_descartan_del_todo():
    """22-sep-2026: a las 04:00 NY la cinta publica lo de la noche con horas de
    retraso; QNME 04:03 salio con 785.000 acciones (oficial 148.000) y cierre
    1,04 (oficial 1,0598). Regla de los 20 ms: publicado > 20 ms despues de
    ejecutarse -> fuera, ni precio ni volumen."""
    c = pre.ConstructorParcial()
    c.aplicar_operacion({**_op(0, 2.00), "pt": BASE})                               # a tiempo
    c.aplicar_operacion({**_op(5, 1.04, tam=500000), "pt": BASE - 3 * 3600 * 1000})  # de la noche
    c.aplicar_operacion({**_op(6, 2.02, tam=100), "pt": BASE + 6000 - 30})           # 30 ms tarde
    c.aplicar_operacion({**_op(7, 2.05, tam=100), "pt": BASE + 7000 - 10})           # 10 ms: a tiempo
    v = c._curso["KXIN"]
    assert (v.open, v.high, v.low, v.close) == (2.00, 2.05, 2.00, 2.05)
    assert v.volumen == 200
    assert c.tardias == 2 and c.v_tardias == 500100


def test_sin_pt_no_se_descarta_nada():
    c = pre.ConstructorParcial()
    c.aplicar_operacion(_op(0, 2.00))
    assert c._curso["KXIN"].volumen == 100 and c.tardias == 0
