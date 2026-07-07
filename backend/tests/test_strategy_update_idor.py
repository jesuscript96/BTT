"""
Regresión del IDOR en update_strategy (hallazgo auditoría 2026-06-27).

Bug original: el PUT /api/strategies/{id} recibía user_id pero NO lo usaba —
ni en el pre-check de existencia ni en el UPDATE — así que cualquier usuario
autenticado podía sobreescribir la estrategia de otro conociendo/adivinando
su id (list/get/delete sí scopean; solo update estaba sin proteger).

Contrato nuevo (mismo patrón que delete_strategy):
- Estrategia de otro usuario → 404 y la fila NO cambia.
- Estrategia propia → 200 y actualiza.
- Fila legacy (user_id NULL, pre-Clerk) → editable por cualquiera
  (scope NULL-tolerante, intencional para no romper datos viejos).
- Sin auth (user_id None, AUTH_ENABLED=false) → comportamiento previo intacto.
"""
import duckdb
import pytest
from fastapi import BackgroundTasks, HTTPException

from app.routers.strategies import create_strategy, update_strategy
from app.schemas.strategy import StrategyCreate

_PAYLOAD = {
    "name": "mia",
    "bias": "short",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": 1.0,
                }
            ],
        },
    },
    "risk_management": {},
}


def _mk(name="mia"):
    return StrategyCreate(**{**_PAYLOAD, "name": name})


def _row(strategy_id):
    con = duckdb.connect("users.duckdb")
    try:
        return con.execute(
            "SELECT name, user_id FROM strategies WHERE id = ?", [strategy_id]
        ).fetchone()
    finally:
        con.close()


@pytest.fixture()
def users_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    con = duckdb.connect("users.duckdb")
    con.execute(
        """
        CREATE TABLE strategies (
            id VARCHAR, name VARCHAR, description VARCHAR,
            created_at TIMESTAMP, updated_at TIMESTAMP,
            definition VARCHAR, user_id VARCHAR
        )
        """
    )
    con.close()


def test_update_estrategia_ajena_devuelve_404_y_no_toca_la_fila(users_db):
    mine = create_strategy(_mk(), BackgroundTasks(), user_id="user_a")
    with pytest.raises(HTTPException) as exc:
        update_strategy(mine.id, _mk("hackeada"), BackgroundTasks(), user_id="user_b")
    assert exc.value.status_code == 404
    assert _row(mine.id) == ("mia", "user_a")


def test_update_estrategia_propia_actualiza(users_db):
    mine = create_strategy(_mk(), BackgroundTasks(), user_id="user_a")
    out = update_strategy(mine.id, _mk("renombrada"), BackgroundTasks(), user_id="user_a")
    assert out.name == "renombrada"
    assert _row(mine.id) == ("renombrada", "user_a")


def test_update_fila_legacy_null_sigue_editable(users_db):
    # Semántica NULL-tolerante intencional: filas pre-Clerk son de todos.
    legacy = create_strategy(_mk("legacy"), BackgroundTasks(), user_id=None)
    out = update_strategy(legacy.id, _mk("editada"), BackgroundTasks(), user_id="user_b")
    assert out.name == "editada"
    assert _row(legacy.id)[0] == "editada"


def test_update_sin_auth_comportamiento_previo(users_db):
    # AUTH_ENABLED=false → user_id None → scope vacío → todo editable (como antes).
    a = create_strategy(_mk(), BackgroundTasks(), user_id="user_a")
    out = update_strategy(a.id, _mk("x"), BackgroundTasks(), user_id=None)
    assert out.name == "x"
