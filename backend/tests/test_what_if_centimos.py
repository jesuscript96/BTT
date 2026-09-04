"""La regla de los céntimos mínimos de las cuentas de fondeo.

QUÉ MODELA. Las mesas de fondeo no abonan un trade que no se haya movido un
mínimo — típicamente 10 céntimos. El backtest no lo modela y no debe hacerlo
(Jaume, 2026-09-04: «mi backtest no modela eso ni quiero que lo haga
directamente»): se aplica en el What-if, para ver cuánto se degrada la curva si
se opera con esas reglas.

LO QUE FIJAN ESTOS TESTS es lo que tiene de traicionero la regla:

  * es ASIMÉTRICA — solo cae sobre los ganadores;
  * es TODO O NADA — al superar el umbral cuenta el beneficio entero, no el
    sobrante;
  * y el caso del borde exacto (1,00 → 0,90) cae del lado de «no cuenta», que
    en coma flotante es justo el que se rompe solo.
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


# ── La regla en sí ───────────────────────────────────────────────────────

def test_el_borde_exacto_NO_cuenta():
    """EL CASO QUE SE ROMPE SOLO. Es el ejemplo de Jaume —short de 1,00 a
    0,90— y en coma flotante 1.00-0.90 sale 0.09999999999999998, así que sin
    tolerancia el resultado depende del azar del binario."""
    assert not mueve_bastante(_t(entrada=1.00, salida=0.90), 0.10)


def test_un_centimo_mas_ya_cuenta():
    assert mueve_bastante(_t(entrada=1.00, salida=0.89), 0.10)


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


def test_sin_precios_no_se_castiga_el_trade():
    """Quitarlo por un hueco de datos nuestro sería castigar la curva por algo
    que no es la regla de la mesa."""
    assert mueve_bastante({"pnl": 100.0}, 0.10)
    assert mueve_bastante(_t(salida=None), 0.10)


# ── Cómo cae sobre la simulación ─────────────────────────────────────────

def test_el_ganador_corto_desaparece_de_la_curva():
    """No es que cuente menos: no cuenta. Ni en equity ni en drawdown."""
    r = run_what_if([_t(entrada=1.00, salida=0.90, pnl=100.0)],
                    {"min_move_cents": 0.10}, init_cash=10_000.0)
    assert r["trades"] == []


def test_el_ganador_largo_se_cuenta_ENTERO():
    """Todo o nada: superado el umbral entra el beneficio completo, no el
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
    recortaba a la mitad el tamaño de los trades abiertos con más de un 5 % de
    drawdown encima. Según dónde cayeran las pérdidas, eso podía MEJORAR la
    curva — y entonces el What-if «sin filtros» salía mejor que el original,
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
        _t(fecha="2026-01-05", entrada=1.00, salida=0.95, pnl=100.0),   # corto
        _t(fecha="2026-01-06", entrada=1.00, salida=0.80, pnl=200.0),   # largo
        _t(fecha="2026-01-07", entrada=1.00, salida=1.03, pnl=-50.0),   # pierde
    ]
    sin = run_what_if(ts, {}, init_cash=10_000.0)
    con = run_what_if(ts, {"min_move_cents": 0.10}, init_cash=10_000.0)
    assert sum(t["pnl"] for t in sin["trades"]) == 250.0
    # Se cae el de 100 (solo 5 céntimos); la pérdida sigue.
    assert sum(t["pnl"] for t in con["trades"]) == 150.0


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
    """Si la regla se lleva todos los trades de un día, ese día desaparece del
    calendario — no se queda en blanco."""
    ts = [_t(fecha="2026-01-05", entrada=1.00, salida=0.90, pnl=100.0),
          _t(fecha="2026-01-06", entrada=1.00, salida=0.50, pnl=300.0)]
    dias = run_what_if(ts, {"min_move_cents": 0.10}, init_cash=10_000.0)["day_results"]
    assert [d["date"] for d in dias] == ["2026-01-06"]


def test_no_se_inventan_las_metricas_que_no_se_pueden_reconstruir():
    """Sharpe y el drawdown intradía salen de la curva del día, que aquí no
    existe. Un cero ahí se leería como «no hubo drawdown», que es falso."""
    d = run_what_if([_t()], {}, init_cash=10_000.0)["day_results"][0]
    assert d["sharpe_ratio"] is None and d["max_drawdown_pct"] is None
    # …y los locates tampoco se arrastran: no hay forma honesta de repartirlos.
    assert d["locates_fee"] == 0.0
