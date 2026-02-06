
from fastapi.testclient import TestClient
from app.main import app
import json

client = TestClient(app)

def test_create_and_get_strategy():
    payload = {
        "name": "Test Strategy Unit",
        "description": "A test strategy for verification",
        "filters": {
            "min_market_cap": 50000000,
            "max_market_cap": 500000000,
            "require_shortable": True,
            "exclude_dilution": True
        },
        "entry_logic": [
            {
                "logic": "AND",
                "conditions": [
                    {
                        "indicator": "Extension",
                        "operator": ">",
                        "value": 15,
                        "compare_to": "EMA9"
                    }
                ]
            }
        ],
        "exit_logic": {
            "stop_loss_type": "Fixed Price",
            "stop_loss_value": 0.5,
            "take_profit_type": "Percent",
            "take_profit_value": 20,
            "trailing_stop_active": True,
            "dilution_profit_boost": False
        }
    }

    # CREATE
    response = client.post("/api/strategies/", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Strategy Unit"
    assert "id" in data
    strategy_id = data["id"]
    
    # GET
    response = client.get(f"/api/strategies/{strategy_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == strategy_id
    assert data["entry_logic"][0]["conditions"][0]["indicator"] == "Extension"
    
    # LIST
    response = client.get("/api/strategies/")
    assert response.status_code == 200
    strategies = response.json()
    assert len(strategies) > 0
    
    # DELETE
    response = client.delete(f"/api/strategies/{strategy_id}")
    assert response.status_code == 200
    
    # VERIFY DELETE
    response = client.get(f"/api/strategies/{strategy_id}")
    assert response.status_code == 404
