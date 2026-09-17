# -*- coding: utf-8 -*-
"""La puerta por EV con EV FIJO, completo o por rango de precio (17-sep-2026).

Una sola definicion (locates_gate) para el backtest, el portfolio en crudo, el
cuadro de mandos y el /evf: aqui se fija que el tramo se resuelve igual en
todos, que un tramo vacio cae al completo y que el modo rodante no cambia.
"""
import numpy as np

from app.services import locates_gate as lg


def test_rangos_normalizados_ordena_limpia_y_conserva_tramos_sin_ev():
    r = lg.rangos_ev_normalizados([
        {"lo": 5, "hi": 10, "ev_pct": 2.5},
        {"lo": 0, "hi": 0.5, "ev_pct": None},
        {"lo": 10, "hi": None, "ev_pct": 0},          # 0 = sin EV
        {"lo": "x", "hi": 1, "ev_pct": 1},            # basura: fuera
        {"lo": 3, "hi": 1, "ev_pct": 1},              # hi <= lo: fuera
        "no soy un dict",
    ])
    assert [x["lo"] for x in r] == [0, 5, 10]
    assert r[0]["ev_pct"] is None and r[1]["ev_pct"] == 2.5 and r[2]["ev_pct"] is None
    assert r[2]["hi"] is None


def test_ev_fijo_para_precio_coge_el_tramo_y_cae_al_completo():
    rangos = [{"lo": 0, "hi": 0.5, "ev_pct": 1.0}, {"lo": 0.5, "hi": 1, "ev_pct": None}, {"lo": 10, "hi": None, "ev_pct": 6.0}]
    assert lg.ev_fijo_para_precio(3.0, rangos, 0.40) == (1.0, "rango")
    assert lg.ev_fijo_para_precio(3.0, rangos, 0.50) == (3.0, "completo")   # tramo vacio
    assert lg.ev_fijo_para_precio(3.0, rangos, 4.00) == (3.0, "completo")   # sin tramo
    assert lg.ev_fijo_para_precio(3.0, rangos, 25.0) == (6.0, "rango")      # sin techo
    assert lg.ev_fijo_para_precio(3.0, [], 25.0) == (3.0, "completo")
    assert lg.ev_fijo_para_precio(None, None, 1.0) == (0.0, "completo")


def test_evaluar_en_modo_fijo_ignora_la_sombra_y_usa_el_tramo():
    # Sombra con senales buenisimas: en modo fijo no se mira.
    cierres = np.arange(1, 41, dtype=np.int64) * lg.NS_POR_DIA
    moves = np.full(40, 50.0)
    cfg = lg.ConfigPuerta(modo="fijo", ev_fijo_pct=3.0,
                          ev_rangos=[{"lo": 0, "hi": 0.5, "ev_pct": 1.0}],
                          sombra_cierre_ns=cierres, sombra_move_pct=moves)
    ahora = int(100 * lg.NS_POR_DIA)
    # 500 acciones a 0,40 $ con paquete a 3 $: fade = 5 paq x 3 / 500 / 0,40 = 7,5 %
    v = lg.evaluar(cfg, ahora, 0.40, 500, 0.0, 3.0)
    assert v["ev_pct"] == 1.0 and v["ev_origen"] == "rango" and v["entra"] is False
    # 500 acciones a 4 $: fade = 15 / 500 / 4 = 0,75 %; EV completo 3 % -> entra
    v = lg.evaluar(cfg, ahora, 4.0, 500, 0.0, 3.0)
    assert v["ev_pct"] == 3.0 and v["ev_origen"] == "completo" and v["entra"] is True
    # y el modo rodante sigue mirando la sombra
    cfg_r = lg.ConfigPuerta(sombra_cierre_ns=cierres, sombra_move_pct=moves)
    v = lg.evaluar(cfg_r, ahora, 0.40, 500, 0.0, 3.0)
    assert v["ev_origen"] == "rodante" and v["ev_pct"] == 50.0 and v["entra"] is True


def test_tramo_vacio_sin_completo_no_entra():
    """El backtest en «por rango» no manda EV completo (0): un tramo sin EV
    no tiene con que compararse y NO entra, ni aunque el locate salga gratis
    (fade 0): 0 > 0 es falso. Es lo que dice la casilla del panel."""
    rangos = [{"lo": 1, "hi": 3, "ev_pct": 4.0}, {"lo": 3, "hi": 5, "ev_pct": None}]
    cfg = lg.ConfigPuerta(modo="fijo", ev_fijo_pct=0.0, ev_rangos=rangos)
    assert lg.ev_fijo_para_precio(0.0, rangos, 4.0) == (0.0, "completo")
    # 4 $ (tramo vacio): fade 15 / 500 / 4 = 0,75 % -> fuera
    assert lg.evaluar(cfg, 0, 4.0, 500, 0.0, 3.0)["entra"] is False
    # 4 $ y ya alquilado (0 paquetes de mas, fade 0): tambien fuera
    assert lg.evaluar(cfg, 0, 4.0, 500, 500.0, 3.0)["entra"] is False
    # 2 $ (tramo con EV 4 %): fade 15 / 500 / 2 = 1,5 % -> entra
    assert lg.evaluar(cfg, 0, 2.0, 500, 0.0, 3.0)["entra"] is True


def test_ventana_cero_es_todo_el_historico():
    cierres = np.arange(1, 101, dtype=np.int64) * lg.NS_POR_DIA
    moves = np.concatenate([np.full(50, 1.0), np.full(50, 9.0)])
    cfg = lg.ConfigPuerta(ventana=0, por="trades", min_trades=10, sombra_cierre_ns=cierres, sombra_move_pct=moves)
    ev, n, defecto = lg.ev_rodante_pct(cfg, int(200 * lg.NS_POR_DIA))
    assert n == 100 and not defecto and abs(ev - 5.0) < 1e-9
    cfg30 = lg.ConfigPuerta(ventana=30, por="trades", min_trades=10, sombra_cierre_ns=cierres, sombra_move_pct=moves)
    ev30, n30, _ = lg.ev_rodante_pct(cfg30, int(200 * lg.NS_POR_DIA))
    assert n30 == 30 and abs(ev30 - 9.0) < 1e-9


def test_movimiento_pct_va_por_el_pnl_y_no_por_la_ultima_salida():
    """Corto a 10 $ x 100 acc: 75 % cerrado a 9 (gana 75 $), el 25 % a EOD a
    10,4 (pierde 10 $). El trade agrupado gana 65 $ brutos pero su
    `exit_price` es 10,4: por el precio de la ultima pierna saldria -4 %;
    por el PnL sobre el nocional, +6,5 %. Es lo que se compara con el fade
    (el coste del locate sobre ese mismo nocional)."""
    t = {"direction": "Short", "avg_entry_price": 10.0, "entry_price": 10.0, "exit_price": 10.4,
         "size": 100.0, "pnl": 65.0 - 1.0, "fees": 1.0, "exit_time_epoch": 1_700_000_000}
    assert abs(lg.movimiento_pct(t) - 6.5) < 1e-9
    # sin pnl/size (registro viejo): cae al precio de salida, como antes
    assert abs(lg.movimiento_pct({"direction": "Short", "entry_price": 10.0, "exit_price": 9.5}) - 5.0) < 1e-9
    assert abs(lg.movimiento_pct({"direction": "Long", "entry_price": 10.0, "exit_price": 9.5}) + 5.0) < 1e-9
    assert lg.movimiento_pct({"direction": "Short", "entry_price": 0.0, "exit_price": 9.5}) is None
    # y la sombra usa esa definicion (solo cortos, ordenada por cierre)
    c, m = lg.sombra_desde_trades([
        {**t, "exit_time_epoch": 20},
        {**t, "direction": "Long", "exit_time_epoch": 15},          # fuera: largo
        {"direction": "Short", "entry_price": 4.0, "exit_price": 3.8, "exit_time_epoch": 10},
    ])
    assert list(c) == [10 * 1_000_000_000, 20 * 1_000_000_000]
    assert abs(m[0] - 5.0) < 1e-9 and abs(m[1] - 6.5) < 1e-9
