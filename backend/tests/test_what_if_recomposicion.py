"""El What-if con riesgo PORCENTUAL: recomponer, no sumar dólares.

EL FALLO QUE FIJAN ESTOS TESTS. Con `risk_type = PERCENT` cada trade arriesga
un % del capital VIVO, así que los dólares que gana dependen del balance que
hubiera ese día. El What-if reconstruía la curva sumando esos dólares, y quitar
trades y volver a sumar el resto rompe el vínculo con el capital: sobre la
corrida real de 3.544 trades la curva acababa en −84.411 $ —dinero negativo—
donde la recomposición da 2.617 $.

La regla de los céntimos de las mesas de fondeo es justo ese caso, y el peor:
descarta ganadores de forma sistemática, no un 10 % puntual. Con la suma en
dólares pintaba la regla mucho más letal de lo que es.

LO QUE NO PUEDE PASAR, y por eso hay un test de cada cosa:

  * que la corrección se active sola y cambie lo que ya había (riesgo FIJO);
  * que un What-if SIN filtros deje de devolver la curva de partida;
  * que la cuenta acabe debiendo dinero.
"""
from app.services.what_if_service import run_what_if


def _t(fecha, pnl, entrada=1.00, salida=0.80, ticker="AAA"):
    """Un trade con lo mínimo que mira el What-if. Por defecto se movió 20
    céntimos, o sea que la regla de la mesa no lo toca."""
    return {
        "ticker": ticker, "date": fecha,
        "entry_time": f"{fecha} 08:00:00", "exit_time": f"{fecha} 08:30:00",
        "entry_weekday": 0, "entry_hour": 8,
        "entry_price": entrada, "exit_price": salida,
        "pnl": pnl, "return_pct": 1.0, "size": 1000.0,
    }


def _final(res):
    return res["global_equity"][-1]["value"]


# Una corrida de dos días: +5.000 el primero, −3.000 el segundo.
# En compuesto el segundo día se dimensiona sobre 15.000, no sobre 10.000.
GANADOR = _t("2026-01-05", 5_000.0)
PERDEDOR = _t("2026-01-06", -3_000.0)


def test_SIN_FILTROS_la_curva_es_la_de_partida():
    """LA INVARIANTE. Sin quitar nada los dos capitales coinciden día a día, el
    factor es 1,0 exacto y la recomposición no puede mover un céntimo. Si esto
    se rompe, el What-if deja de ser comparable con el backtest."""
    aditivo = run_what_if([GANADOR, PERDEDOR], {}, init_cash=10_000.0)
    compuesto = run_what_if([GANADOR, PERDEDOR], {"risk_type": "PERCENT"},
                            init_cash=10_000.0)
    assert _final(compuesto) == _final(aditivo) == 12_000.0


def test_al_quitar_un_ganador_el_resto_se_reescala():
    """EL FALLO EN UNA LÍNEA. Quitado el ganador del día 1, el perdedor del
    día 2 ya no se dimensiona sobre 15.000 $ sino sobre 10.000: pierde dos
    tercios de lo que perdió, no los 3.000 $ enteros.

        factor = 10.000 / 15.000 = 0,667  →  −3.000 × 0,667 = −2.000
    """
    corto = _t("2026-01-05", 5_000.0, entrada=1.00, salida=0.95)  # 5 céntimos
    r = run_what_if([corto, PERDEDOR],
                    {"min_move_cents": 0.10, "risk_type": "PERCENT"},
                    init_cash=10_000.0)
    assert len(r["trades"]) == 1
    assert round(_final(r), 2) == 8_000.00


def test_el_riesgo_FIJO_sigue_sumando_dolares():
    """En aditivo los dólares de un trade no dependen del balance, así que
    sumarlos ya era correcto. La corrección NO puede activarse sola: sin
    `risk_type` el resultado es el de siempre."""
    corto = _t("2026-01-05", 5_000.0, entrada=1.00, salida=0.95)
    r = run_what_if([corto, PERDEDOR], {"min_move_cents": 0.10},
                    init_cash=10_000.0)
    assert round(_final(r), 2) == 7_000.00


def test_la_cuenta_no_puede_acabar_debiendo_dinero():
    """Lo contrario de lo que hacía la suma en dólares, que llegó a pintar
    −84.411 $ sobre una cuenta de 10.000."""
    ganador = _t("2026-01-05", 40_000.0, entrada=1.00, salida=0.95)  # se cae
    ruina = _t("2026-01-06", -45_000.0)
    mas_tarde = _t("2026-01-07", -10_000.0)
    r = run_what_if([ganador, ruina, mas_tarde],
                    {"min_move_cents": 0.10, "risk_type": "PERCENT"},
                    init_cash=10_000.0)
    assert min(p["value"] for p in r["global_equity"]) >= 0.0


def test_el_drawdown_no_pasa_del_100_por_cien():
    """El síntoma que se veía en pantalla: drawdowns de −567 %."""
    ganador = _t("2026-01-05", 40_000.0, entrada=1.00, salida=0.95)
    ruina = _t("2026-01-06", -45_000.0)
    r = run_what_if([ganador, ruina],
                    {"min_move_cents": 0.10, "risk_type": "PERCENT"},
                    init_cash=10_000.0)
    assert min(p["value"] for p in r["global_drawdown"]) >= -100.0


# ── Los locates: por qué el What-if salía MEJOR que el original ──────────

def _con_locate(fecha, pnl, ticker="AAA", **kw):
    t = _t(fecha, pnl, **kw)
    t["ticker"] = ticker
    return t


LOCATES = {"AAA|2026-01-05": 400.0, "AAA|2026-01-06": 400.0}


def test_los_locates_se_descuentan_de_la_curva():
    """EL FALLO QUE VIO JAUME EN PANTALLA. La curva del backtest va NETA de
    locates; la del What-if iba BRUTA, porque el locate no está en el pnl de
    ningún trade y no llegaba por ningún sitio. La simulación salía mejor que
    el original por el importe entero del alquiler, y una regla que solo QUITA
    ganadores parecía mejorar la estrategia."""
    ts = [_con_locate("2026-01-05", 5_000.0), _con_locate("2026-01-06", -3_000.0)]
    sin = run_what_if(ts, {}, init_cash=10_000.0)
    con = run_what_if(ts, {"locates_by_pair": LOCATES}, init_cash=10_000.0)
    assert _final(sin) == 12_000.0
    assert _final(con) == 11_200.0          # 12.000 − 800 de alquiler


def test_el_locate_del_dia_que_se_queda_sin_trades_no_se_paga():
    """Se cobra por ticker-día: si no sobrevive ningún trade de ese ticker ese
    día, no se alquiló nada. Y si sobrevive alguno, se debe ENTERO."""
    corto = _con_locate("2026-01-05", 5_000.0, entrada=1.00, salida=0.95)
    r = run_what_if([corto, _con_locate("2026-01-06", -3_000.0)],
                    {"min_move_cents": 0.10, "locates_by_pair": LOCATES},
                    init_cash=10_000.0)
    assert len(r["trades"]) == 1
    assert _final(r) == 6_600.0             # 10.000 − 3.000 − 400 del día vivo
    assert r["day_results"][0]["locates_fee"] == 400.0
