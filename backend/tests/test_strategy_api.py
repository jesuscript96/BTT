"""Alta, lectura, listado y borrado de una estrategia por la API.

ESTE TEST ERA UN FOSIL. Mandaba `entry_logic` como una LISTA de bloques
`{logic, conditions}` con condiciones `{indicator, operator, value, compare_to}`,
un `filters` que hoy se llama `universe_filters`, un `exit_logic` plano de
`stop_loss_type` / `take_profit_value`, y NINGUN `risk_management` — que es
obligatorio. O sea, la API de hace varias versiones.

El backend respondia 422 y hacia bien: el payload no valida. El test llevaba
meses en rojo pareciendo un fallo del servidor cuando el roto era el.

FORMATO DE HOY (ver `app/schemas/strategy.py`): `entry_logic` y `exit_logic` son
objetos con `timeframe` y un `root_condition` en arbol, y el riesgo va aparte en
`risk_management`.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _payload(nombre="Test Strategy Unit"):
    return {
        "name": nombre,
        "description": "A test strategy for verification",
        "bias": "long",
        "universe_filters": {
            "min_market_cap": 50_000_000,
            "max_market_cap": 500_000_000,
        },
        "entry_logic": {
            "timeframe": "1m",
            "candle_delay": 1,
            "root_condition": {
                "operator": "AND",
                "conditions": [{
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": {"name": "VWAP"},
                }],
            },
        },
        "exit_logic": {
            "timeframe": "1m",
            "root_condition": {"operator": "AND", "conditions": []},
        },
        "risk_management": {
            "use_hard_stop": True,
            "hard_stop": {"type": "Percentage", "value": 5.0},
            "use_take_profit": True,
            "take_profit": {"type": "Percentage", "value": 20.0},
            "accept_reentries": False,
        },
    }


def test_create_and_get_strategy():
    # CREATE
    response = client.post("/api/strategies/", json=_payload())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["name"] == "Test Strategy Unit"
    assert "id" in data
    strategy_id = data["id"]

    # GET — y que la condicion vuelve entera, no solo que existe la fila:
    # guardar la estrategia perdiendo su arbol seria un fallo callado.
    response = client.get(f"/api/strategies/{strategy_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == strategy_id
    cond = data["entry_logic"]["root_condition"]["conditions"][0]
    assert cond["source"]["name"] == "Bar Close"
    assert cond["target"]["name"] == "VWAP"

    # LIST
    response = client.get("/api/strategies/")
    assert response.status_code == 200
    assert len(response.json()) > 0

    # DELETE
    response = client.delete(f"/api/strategies/{strategy_id}")
    assert response.status_code == 200

    # VERIFY DELETE
    response = client.get(f"/api/strategies/{strategy_id}")
    assert response.status_code == 404


def test_create_rechaza_el_formato_antiguo():
    """El formato viejo tiene que seguir dando 422, no colarse a medias.

    Con `extra="ignore"` de pydantic, un payload que no encaja puede perder
    campos EN SILENCIO en vez de fallar — el patron que mas muerde en este
    repo. Aqui se comprueba que la puerta esta cerrada del todo.
    """
    antiguo = {
        "name": "formato viejo",
        "filters": {"min_market_cap": 1},
        "entry_logic": [{"logic": "AND", "conditions": [
            {"indicator": "Extension", "operator": ">", "value": 15, "compare_to": "EMA9"}]}],
        "exit_logic": {"stop_loss_type": "Fixed Price", "stop_loss_value": 0.5},
    }
    assert client.post("/api/strategies/", json=antiguo).status_code == 422
