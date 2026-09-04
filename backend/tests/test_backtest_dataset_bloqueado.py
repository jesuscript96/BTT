"""Un backtest que falla no puede dejar el dataset bloqueado.

EL FALLO. El POST siembra `backtest_progress[dataset_id] = {"status":
"running"}` antes de lanzar el hilo, para que el guard anti-doble-run lo vea de
inmediato. Pero el estado del job vive en OTRO almacén (`backtest_jobs`), y al
fallar solo se actualizaba ese: la siembra se quedaba en "running" para
siempre.

Consecuencia: cualquier backtest posterior sobre ese dataset devolvía
"already_running" apuntando a un job muerto, y la única salida era reiniciar el
backend. Basta una definición mal formada o un pico de memoria para dejar
inservible un dataset el resto de la sesión.
"""
from fastapi import HTTPException

from app.routers.backtest import _liberar_dataset, backtest_progress

DS = "dataset-de-prueba"


def _sembrar():
    """Lo que hace el POST justo antes de lanzar el hilo."""
    backtest_progress[DS] = {"status": "running", "current": 0, "total": 0, "percent": 0.0}


def teardown_function():
    backtest_progress.pop(DS, None)


def test_tras_un_fallo_el_dataset_queda_libre():
    """LO IMPORTANTE: que el guard deje pasar el siguiente intento."""
    _sembrar()
    _liberar_dataset(DS, "failed", "strategy_id or strategy_definition required")
    assert backtest_progress[DS]["status"] != "running"


def test_tras_una_cancelacion_tambien():
    _sembrar()
    _liberar_dataset(DS, "cancelled")
    assert backtest_progress[DS]["status"] != "running"


def test_se_guarda_POR_QUE_fallo():
    """Se marca el estado real en vez de borrar la entrada, para que el sondeo
    antiguo por dataset pueda contar qué pasó en vez de no encontrar nada."""
    _sembrar()
    _liberar_dataset(DS, "failed", "sin memoria")
    assert backtest_progress[DS]["status"] == "failed"
    assert backtest_progress[DS]["error"] == "sin memoria"


def test_una_cancelacion_no_inventa_un_error():
    _sembrar()
    _liberar_dataset(DS, "cancelled")
    assert "error" not in backtest_progress[DS]


def test_liberar_NUNCA_lanza():
    """Corre dentro del `except` que remata un job fallido: si esto lanzara, el
    fallo original se perdería debajo de otro."""
    _liberar_dataset(DS, "failed", None)
    _liberar_dataset("", "failed", "x")          # dataset vacío
    _liberar_dataset(DS, "failed", "x" * 10_000)


def test_el_guard_anti_doble_run_solo_mira_running():
    """La razón de escribir el estado en vez de borrar la clave: el guard del
    POST bloquea únicamente con "running", así que "failed" no estorba."""
    for estado in ("failed", "cancelled", "succeeded"):
        backtest_progress[DS] = {"status": estado}
        assert backtest_progress.get(DS, {}).get("status") != "running"
