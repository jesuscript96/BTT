
import unittest
import json
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db

class TestStrategyAPI(unittest.TestCase):
    def setUp(self):
        # Force DB init for tests
        init_db()
        self.client = TestClient(app)

    def test_create_and_get_strategy(self):
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
        print("\nTesting POST /api/strategies/ ...")
        response = self.client.post("/api/strategies/", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Test Strategy Unit")
        self.assertIn("id", data)
        strategy_id = data["id"]
        print(f"Created Strategy ID: {strategy_id}")
        
        # GET
        print(f"Testing GET /api/strategies/{strategy_id} ...")
        response = self.client.get(f"/api/strategies/{strategy_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], strategy_id)
        self.assertEqual(data["entry_logic"][0]["conditions"][0]["indicator"], "Extension")
        print("GET verification successful.")
        
        # LIST
        print("Testing LIST /api/strategies/ ...")
        response = self.client.get("/api/strategies/")
        self.assertEqual(response.status_code, 200)
        strategies = response.json()
        self.assertTrue(len(strategies) > 0)
        print(f"Found {len(strategies)} strategies.")
        
        # DELETE
        print(f"Testing DELETE /api/strategies/{strategy_id} ...")
        response = self.client.delete(f"/api/strategies/{strategy_id}")
        self.assertEqual(response.status_code, 200)
        
        # VERIFY DELETE
        response = self.client.get(f"/api/strategies/{strategy_id}")
        self.assertEqual(response.status_code, 404)
        print("Delete verification successful.")

if __name__ == '__main__':
    unittest.main()
