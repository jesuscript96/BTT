"""La regla de los céntimos, también en el motor de Robustez.

POR QUÉ AQUÍ TAMBIÉN. La regla vivía solo en el What-if, que reconstruye la
curva sumando dólares; el módulo de Robustez tiene su propio motor que trabaja
en R y recompone por día, que es el dominio correcto cuando el riesgo es un %
del capital vivo. Tener la regla solo en el motor aditivo era tenerla en el
sitio equivocado.

La función que decide se importa del What-if a propósito: es UNA regla de una
mesa de fondeo, y escribirla dos veces es garantizar que un día las dos
pantallas digan cosas distintas del mismo histórico.
"""
from app.services.robustness_stress import run_stress


def _t(fecha, hora, pnl, r, entrada=1.00, salida=0.80):
    return {
        "ticker": "AAA", "date": fecha,
        "entry_time": f"{fecha} {hora}:00", "exit_time": f"{fecha} {hora}:30",
        "entry_price": entrada, "exit_price": salida,
        "pnl": pnl, "r_multiple": r, "return_pct": r * 10.0,
        "size": 1000.0, "stop_loss": entrada * 0.9,
    }


BASE = [
    _t("2026-01-05", "08:00", 300.0, 1.0),                       # 20 cts
    _t("2026-01-06", "08:00", 300.0, 1.0, salida=0.95),          # 5 cts
    _t("2026-01-07", "08:00", -300.0, -1.0, salida=1.02),        # 2 cts, pierde
]


def test_el_ganador_que_no_se_movio_desaparece():
    r = run_stress(BASE, {"min_move_cents": 0.10}, init_cash=10_000.0,
                   risk_pct=3.0)
    assert r["trades_removed"] == 1
    assert r["trades_kept"] == 2


def test_las_perdidas_se_cuentan_aunque_no_se_muevan():
    """Lo asimétrico de la regla: es lo que la hace doler."""
    solo_perdida = [_t("2026-01-07", "08:00", -300.0, -1.0, salida=1.02)]
    r = run_stress(solo_perdida, {"min_move_cents": 0.10}, init_cash=10_000.0)
    assert r["trades_removed"] == 0


def test_a_cero_no_castiga_nada():
    r = run_stress(BASE, {"min_move_cents": 0}, init_cash=10_000.0)
    assert r["trades_removed"] == 0
    assert r["stressed"]["final_balance"] == r["base"]["final_balance"]


def test_el_castigo_se_recompone_y_no_pasa_del_100_por_cien():
    """La razón de portarla aquí: en R la cuenta no puede acabar en negativo."""
    r = run_stress(BASE, {"min_move_cents": 0.10}, init_cash=10_000.0,
                   mode="compound", risk_pct=3.0)
    assert r["stressed"]["max_drawdown_pct"] >= -100.0
    assert r["stressed"]["final_balance"] > 0
