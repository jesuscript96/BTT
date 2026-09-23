"""Tags de organización de estrategias (PATCH /api/strategies/{id}/tags).

Peticion de Alvaro 2026-09-23: etiquetas libres para encontrar y agrupar las
estrategias guardadas. Contrato:
- Sustituyen la lista completa (el frontend manda el estado final).
- Solo metadato: el PUT de la definicion NO las toca.
- Sanitización estricta en la frontera: trim, sin vacíos, dedupe
  case-insensitive, máx 10 tags de 24 caracteres; el primer problema es un
  400 explícito — nada de recortar en silencio.
- Mismo scoping que el resto de endpoints: estrategia ajena → 404 y fila
  intacta (lección IDOR de update, 2026-06-27).
"""
import duckdb
import pytest
from fastapi import BackgroundTasks, HTTPException

from app.routers.strategies import (
    create_strategy,
    get_strategy,
    list_strategies,
    set_strategy_tags,
    update_strategy,
)
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


def _col(strategy_id):
    con = duckdb.connect("users.duckdb")
    try:
        return con.execute(
            "SELECT tags FROM strategies WHERE id = ?", [strategy_id]
        ).fetchone()[0]
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
            definition VARCHAR, user_id VARCHAR, tags VARCHAR,
            in_incubator BOOLEAN
        )
        """
    )
    con.close()


def test_roundtrip_patch_y_lectura(users_db):
    mine = create_strategy(_mk(), BackgroundTasks(), user_id="user_a")
    # Nace sin etiquetas.
    assert get_strategy(mine.id, user_id="user_a")["tags"] == []

    out = set_strategy_tags(
        mine.id, type("B", (), {"tags": ["scalping", " pre "]})(),
        BackgroundTasks(), user_id="user_a",
    )
    assert out["tags"] == ["scalping", "pre"]
    assert get_strategy(mine.id, user_id="user_a")["tags"] == ["scalping", "pre"]
    listed = [s for s in list_strategies(user_id="user_a") if s["id"] == mine.id]
    assert listed[0]["tags"] == ["scalping", "pre"]


def test_sustituye_la_lista_completa(users_db):
    mine = create_strategy(_mk(), BackgroundTasks(), user_id="user_a")
    set_strategy_tags(
        mine.id, type("B", (), {"tags": ["a", "b"]})(), BackgroundTasks(), user_id="user_a"
    )
    set_strategy_tags(
        mine.id, type("B", (), {"tags": []})(), BackgroundTasks(), user_id="user_a"
    )
    assert get_strategy(mine.id, user_id="user_a")["tags"] == []


def test_saneo_trim_dedupe_y_tope(users_db):
    mine = create_strategy(_mk(), BackgroundTasks(), user_id="user_a")
    out = set_strategy_tags(
        mine.id,
        type("B", (), {"tags": [" Scalping ", "scalping", "", "  ", "versión-2"]})(),
        BackgroundTasks(), user_id="user_a",
    )
    # trim, vacíos fuera, dedupe case-insistente conservando la primera.
    assert out["tags"] == ["Scalping", "versión-2"]

    once = [f"t{i}" for i in range(12)]
    out = set_strategy_tags(
        mine.id, type("B", (), {"tags": once})(), BackgroundTasks(), user_id="user_a"
    )
    assert out["tags"] == once[:10]


def test_tag_demasiado_largo_es_400(users_db):
    mine = create_strategy(_mk(), BackgroundTasks(), user_id="user_a")
    with pytest.raises(HTTPException) as exc:
        set_strategy_tags(
            mine.id, type("B", (), {"tags": ["x" * 25]})(),
            BackgroundTasks(), user_id="user_a",
        )
    assert exc.value.status_code == 400
    # La fila no se tocó.
    assert _col(mine.id) is None


def test_estrategia_ajena_devuelve_404_y_no_toca_la_fila(users_db):
    mine = create_strategy(_mk(), BackgroundTasks(), user_id="user_a")
    with pytest.raises(HTTPException) as exc:
        set_strategy_tags(
            mine.id, type("B", (), {"tags": ["hack"]})(), BackgroundTasks(), user_id="user_b"
        )
    assert exc.value.status_code == 404
    assert _col(mine.id) is None


def test_el_put_de_la_definicion_no_pisa_las_tags(users_db):
    mine = create_strategy(_mk(), BackgroundTasks(), user_id="user_a")
    set_strategy_tags(
        mine.id, type("B", (), {"tags": ["jjaume"]})(), BackgroundTasks(), user_id="user_a"
    )
    updated = update_strategy(mine.id, _mk("v2"), BackgroundTasks(), user_id="user_a")
    # El echo del PUT devuelve las tags que había (no las borra ni las pierde).
    assert updated.tags == ["jjaume"]
    assert get_strategy(mine.id, user_id="user_a")["tags"] == ["jjaume"]
