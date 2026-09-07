"""La regla de los céntimos mínimos de las cuentas de fondeo.

QUÉ MODELA. Las mesas de fondeo no abonan un trade que no se haya movido un
mínimo — típicamente 10 céntimos. El backtest no lo modela y no debe hacerlo
(Jaume, 2026-09-04: «mi backtest no modela eso ni quiero que lo haga
directamente»): se aplica en el What-if, para ver cuánto se degrada la curva si
se opera con esas reglas.

LO QUE FIJAN ESTOS TESTS es lo que tiene de traicionero la regla:

  * es ASIMÉTRICA — solo cae sobre los ganadores;
  * es TODO O NADA — al llegar al umbral cuenta el beneficio entero, no el
    sobrante;
  * el BORDE EXACTO CUENTA (1,00 → 0,90 son 10 justos): la norma de TTP dice
    «at least 10 price ticks» y su ejemplo canónico es compra 50.10 venta
    «50.20 (at least)». Corregido el 2026-09-07: antes caía del lado de «no
    cuenta» por la lectura de «supera»;
  * el recorrido se mide ENTRE MEDIAS — precio medio de entrada contra precio
    medio de salida (cada venta por sus acciones), no contra la última venta
    (corregido el 2026-09-07);
  * y el ganador invalidado NO desaparece: la mesa le cobra igualmente las
    comisiones, así que se queda en la curva pagando solo sus fees (decisión
    de Álvaro, 2026-09-07).
"""
from app.services.what_if_service import mueve_bastante, run_what_if


def _t(ticker="AAA", fecha="2026-01-05", entrada=1.00, salida=0.90, pnl=100.0,
       **extra):
    """Un trade con lo mínimo que mira el What-if."""
    t = {
        "ticker": ticker, "date": fecha,
        "entry_time": f"{fecha} 08:00:00", "exit_time": f"{fecha} 08:30:00",
        "entry_weekday": 0, "entry_hour": 8,
        "entry_price": entrada, "exit_price": salida,
        "pnl": pnl, "return_pct": 1.0, "size": 1000.0,
    }
    t.update(extra)
    return t


def _exe(kind, precio, size, t, label="Salida"):
    """Una ejecución del detalle `executions[]` de un trade agrupado."""
    return {"kind": kind, "time_epoch": t, "price": precio, "size": size,
            "pnl": 0.0, "label": label}


# ── La regla en sí ───────────────────────────────────────────────────────

def test_el_borde_exacto_SI_cuenta():
    """EL CASO QUE SE ROMPE SOLO. La norma dice «at least»: un short de 1,00 a
    0,90 son 10 céntimos justos y cuentan. Y en coma flotante 1.00-0.90 sale
    0.09999999999999998, así que sin tolerancia el resultado depende del azar
    del binario."""
    assert mueve_bastante(_t(entrada=1.00, salida=0.90), 0.10)


def test_un_centimo_mas_ya_cuenta():
    assert mueve_bastante(_t(entrada=1.00, salida=0.89), 0.10)


def test_un_centimo_menos_no_cuenta():
    """0,91 deja el recorrido en 9 céntimos: por debajo del umbral, no se abona."""
    assert not mueve_bastante(_t(entrada=1.00, salida=0.91), 0.10)


def test_da_igual_la_direccion():
    """En corto el precio baja y en largo sube; la mesa exige distancia."""
    assert mueve_bastante(_t(entrada=1.00, salida=0.85), 0.10)   # short
    assert mueve_bastante(_t(entrada=1.00, salida=1.15), 0.10)   # largo


def test_con_piramide_manda_el_precio_MEDIO():
    """El recorrido que cuenta es desde donde quedó la posición, no desde el
    primer trozo: con pirámide el precio medio es otro."""
    # Primer trozo a 1,00 pero la posición quedó a 0,95: a 0,90 solo recorrió 5.
    assert not mueve_bastante(
        _t(entrada=1.00, salida=0.90, avg_entry_price=0.95), 0.10)


def test_la_salida_es_la_MEDIA_de_las_ventas():
    """TTP publica la regla como «difference between average entry and AVERAGE
    EXIT price»: cada venta cuenta por sus acciones. Dos casos donde mirar
    solo la ÚLTIMA venta da el veredicto equivocado, cada uno en un sentido."""
    # Media 0,818 (recorrió 18¢): cuenta. La última venta sola (0,98 → 2¢)
    # habría dicho que no.
    t = _t(entrada=1.00, salida=0.98,
           executions=[_exe("entry", 1.00, 1000, 1, "Entrada"),
                       _exe("exit", 0.80, 900, 2),
                       _exe("exit", 0.98, 100, 3)])
    assert mueve_bastante(t, 0.10)
    # Media 0,905 (recorrió 9,5¢): NO cuenta. La última venta sola (0,80 → 20¢)
    # lo habría dado por bueno.
    t = _t(entrada=1.00, salida=0.80,
           executions=[_exe("entry", 1.00, 1000, 1, "Entrada"),
                       _exe("exit", 0.95, 700, 2),
                       _exe("exit", 0.80, 300, 3)])
    assert not mueve_bastante(t, 0.10)


def test_sin_precios_no_se_castiga_el_trade():
    """Quitarlo por un hueco de datos nuestro sería castigar la curva por algo
    que no es la regla de la mesa."""
    assert mueve_bastante({"pnl": 100.0}, 0.10)
    assert mueve_bastante(_t(salida=None), 0.10)


# ── Cómo cae sobre la simulación ─────────────────────────────────────────

def test_el_win_invalidado_se_queda_pagando_solo_sus_fees():
    """La mesa no abona el beneficio, pero las comisiones las cobra igual
    (sus Program Terms las listan como deducción siempre). El trade no
    desaparece de la curva: queda como un pequeño error de comisiones."""
    t = _t(entrada=1.00, salida=0.95, pnl=100.0, fees=7.0)
    r = run_what_if([t], {"min_move_cents": 0.10}, init_cash=10_000.0)
    assert len(r["trades"]) == 1
    assert r["trades"][0]["pnl"] == -7.0
    # El trade de entrada no se muta.
    assert t["pnl"] == 100.0


def test_el_ganador_largo_se_cuenta_ENTERO():
    """Todo o nada: llegado al umbral entra el beneficio completo, no el
    sobrante por encima de los 10 céntimos."""
    r = run_what_if([_t(entrada=1.00, salida=0.80, pnl=200.0)],
                    {"min_move_cents": 0.10}, init_cash=10_000.0)
    assert len(r["trades"]) == 1
    assert r["trades"][0]["pnl"] == 200.0


def test_LAS_PERDIDAS_SE_CUENTAN_IGUAL_aunque_no_se_muevan():
    """LO IMPORTANTE, y lo que hace que esta regla duela.

    La mesa no te abona el ganador que no se movió, pero el perdedor que
    tampoco se movió te lo apunta entero. Modelarla simétrica pintaría la curva
    mejor de lo que la cuenta va a ir de verdad.
    """
    perdedor = _t(entrada=1.00, salida=1.02, pnl=-50.0)
    r = run_what_if([perdedor], {"min_move_cents": 0.10}, init_cash=10_000.0)
    assert len(r["trades"]) == 1 and r["trades"][0]["pnl"] == -50.0


def test_sin_la_opcion_no_cambia_nada():
    """A cero, el What-if se comporta como antes de existir esto."""
    ts = [_t(entrada=1.00, salida=0.90, pnl=100.0)]
    assert len(run_what_if(ts, {}, init_cash=10_000.0)["trades"]) == 1
    assert len(run_what_if(ts, {"min_move_cents": 0}, init_cash=10_000.0)["trades"]) == 1


def test_SIN_NINGUN_FILTRO_LA_CURVA_ES_LA_ORIGINAL():
    """LA PROPIEDAD QUE FALTABA, y que se estaba incumpliendo.

    `dd_threshold` venía por defecto en 5 y `size_mgmt_type` en "dd", y la
    página no manda ninguno de los dos: toda simulación, sin marcar nada,
    recortaba a la mitad el tamaño de los trades abiertos con más de un 5 %
    de drawdown encima. Según dónde cayeran las pérdidas, eso podía MEJORAR
    la curva — y entonces el What-if «sin filtros» salía mejor que el original,
    que es imposible y es lo que vio Jaume (2026-09-04).

    Un What-if sin opciones tiene que devolver la curva de partida. Si no, no
    hay contra qué comparar.
    """
    ts = []
    for i, pnl in enumerate([300.0, -400.0, -350.0, 500.0, 250.0]):
        d = f"2026-01-{5 + i:02d}"
        ts.append(_t(fecha=d, pnl=pnl, entrada=1.0, salida=0.5))
    r = run_what_if([dict(t) for t in ts], {}, init_cash=10_000.0)
    assert len(r["trades"]) == len(ts)
    assert [x["pnl"] for x in r["trades"]] == [t["pnl"] for t in ts]
    assert sum(x["pnl"] for x in r["trades"]) == sum(t["pnl"] for t in ts)


def test_la_gestion_de_tamano_sigue_funcionando_cuando_SE_PIDE():
    """Apagarla por defecto no es quitarla: pedida, recorta como siempre."""
    ts = []
    for i, pnl in enumerate([300.0, -400.0, -350.0, 500.0, 250.0]):
        d = f"2026-01-{5 + i:02d}"
        ts.append(_t(fecha=d, pnl=pnl, entrada=1.0, salida=0.5))
    r = run_what_if([dict(t) for t in ts],
                    {"size_mgmt_type": "dd", "dd_threshold": 5, "dd_reduction": 50},
                    init_cash=10_000.0)
    assert sum(x["pnl"] for x in r["trades"]) != sum(t["pnl"] for t in ts)


def test_la_curva_se_degrada_de_verdad():
    """El caso que quiere ver Jaume: cuánto se cae la cuenta con la regla."""
    ts = [
        _t(fecha="2026-01-05", entrada=1.00, salida=0.95, pnl=100.0, fees=10.0),  # corto
        _t(fecha="2026-01-06", entrada=1.00, salida=0.80, pnl=200.0),   # largo
        _t(fecha="2026-01-07", entrada=1.00, salida=1.03, pnl=-50.0),   # pierde
    ]
    sin = run_what_if(ts, {}, init_cash=10_000.0)
    con = run_what_if(ts, {"min_move_cents": 0.10}, init_cash=10_000.0)
    assert sum(t["pnl"] for t in sin["trades"]) == 250.0
    # El de 100 solo recorrió 5¢: no se abona y queda pagando sus 10 de fees;
    # la pérdida sigue entera.
    assert con["trades"][0]["pnl"] == -10.0
    assert sum(t["pnl"] for t in con["trades"]) == 140.0


# ── El calendario del What-if ────────────────────────────────────────────

def test_devuelve_dias_para_el_calendario():
    """Los arma el backend y no la página para que el calendario del What-if y
    el de siempre no puedan decir cosas distintas del mismo día."""
    ts = [_t(fecha="2026-01-05", pnl=100.0, entrada=1.0, salida=0.5),
          _t(fecha="2026-01-05", pnl=-40.0, entrada=1.0, salida=1.2),
          _t(fecha="2026-01-06", pnl=70.0, entrada=1.0, salida=0.5)]
    dias = run_what_if(ts, {}, init_cash=10_000.0)["day_results"]
    assert [d["date"] for d in dias] == ["2026-01-05", "2026-01-06"]
    assert dias[0]["total_trades"] == 2 and dias[0]["win_rate_pct"] == 50.0
    assert dias[1]["total_trades"] == 1


def test_los_dias_reflejan_el_filtro():
    """El día del win invalidado NO desaparece del calendario: el trade se
    queda pagando solo sus fees. (Antes el trade se eliminaba entero y el día
    se esfumaba.)"""
    ts = [_t(fecha="2026-01-05", entrada=1.00, salida=0.95, pnl=100.0, fees=10.0),
          _t(fecha="2026-01-06", entrada=1.00, salida=0.50, pnl=300.0)]
    r = run_what_if(ts, {"min_move_cents": 0.10}, init_cash=10_000.0)
    dias = r["day_results"]
    assert [d["date"] for d in dias] == ["2026-01-05", "2026-01-06"]
    assert dias[0]["total_trades"] == 1
    # El día del invalidado queda en −10 (sus fees), no en +100 ni esfumado.
    assert dias[0]["expectancy"] == -10.0


def test_no_se_inventan_las_metricas_que_no_se_pueden_reconstruir():
    """Sharpe y el drawdown intradía salen de la curva del día, que aquí no
    existe. Un cero ahí se leería como «no hubo drawdown», que es falso."""
    d = run_what_if([_t()], {}, init_cash=10_000.0)["day_results"][0]
    assert d["sharpe_ratio"] is None and d["max_drawdown_pct"] is None
    # …y los locates tampoco se arrastran: no hay forma honesta de repartirlos.
    assert d["locates_fee"] == 0.0
