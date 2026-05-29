"""
Seed mock data into users.duckdb for local development.
Inserts sample datasets (saved_queries) and strategies so the UI dropdowns
are populated without needing MotherDuck or GCS.
"""

import json
import uuid
from datetime import datetime


def _generate_id() -> str:
    return str(uuid.uuid4())


MOCK_DATASETS = [
    {
        "id": "mock_dataset_1",
        "name": "Small Caps Gappers > 20% (2023-2024)",
        "filters": json.dumps({
            "date_from": "2023-01-01",
            "date_to": "2024-12-31",
            "min_gap_pct": 20.0,
            "max_gap_pct": None,
            "min_rth_volume": 500000,
            "rules": []
        }),
    },
    {
        "id": "mock_dataset_2",
        "name": "Large Caps Earnings Gaps 5-15% (2024)",
        "filters": json.dumps({
            "date_from": "2024-01-01",
            "date_to": "2024-12-31",
            "min_gap_pct": 5.0,
            "max_gap_pct": 15.0,
            "min_rth_volume": 1000000,
            "rules": []
        }),
    },
    {
        "id": "mock_dataset_3",
        "name": "All Gaps > 10% (2022-2024)",
        "filters": json.dumps({
            "date_from": "2022-01-01",
            "date_to": "2024-12-31",
            "min_gap_pct": 10.0,
            "rules": []
        }),
    },
]

MOCK_STRATEGIES = [
    {
        "id": "mock_strategy_1",
        "name": "VWAP Reclaim Long",
        "description": "Entra largo cuando precio cruza VWAP por arriba con volumen > media",
        "definition": json.dumps({
            "name": "VWAP Reclaim Long",
            "bias": "long",
            "entry_logic": {
                "timeframe": "1m",
                "root_condition": {
                    "type": "group",
                    "operator": "AND",
                    "conditions": [
                        {
                            "type": "indicator_comparison",
                            "source": {"name": "Bar Close"},
                            "comparator": "CROSSES_ABOVE",
                            "target": {"name": "VWAP"},
                            "timeframe": "1m"
                        },
                        {
                            "type": "indicator_comparison",
                            "source": {"name": "Volume"},
                            "comparator": "GREATER_THAN",
                            "target": {"name": "SMA", "period": 20},
                            "timeframe": "1m"
                        }
                    ]
                }
            },
            "exit_logic": {
                "timeframe": "1m",
                "root_condition": {
                    "type": "group",
                    "operator": "AND",
                    "conditions": []
                }
            },
            "risk_management": {
                "use_hard_stop": True,
                "use_take_profit": True,
                "take_profit_mode": "Full",
                "accept_reentries": True,
                "hard_stop": {"type": "Percentage", "value": 3.0},
                "take_profit": {"type": "Percentage", "value": 6.0},
                "partial_take_profits": [],
                "trailing_stop": {"active": False, "type": "Percentage", "buffer_pct": 0.5}
            }
        }),
    },
    {
        "id": "mock_strategy_2",
        "name": "Opening Range Breakdown Short",
        "description": "Corto al romper mínimo del rango de apertura de 15 min",
        "definition": json.dumps({
            "name": "Opening Range Breakdown Short",
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
                            "comparator": "LESS_THAN",
                            "target": {"name": "Opening range -", "orb_minutes": 15},
                            "timeframe": "1m"
                        }
                    ]
                }
            },
            "exit_logic": {
                "timeframe": "1m",
                "root_condition": {
                    "type": "group",
                    "operator": "AND",
                    "conditions": []
                }
            },
            "risk_management": {
                "use_hard_stop": True,
                "use_take_profit": True,
                "take_profit_mode": "Full",
                "accept_reentries": False,
                "hard_stop": {"type": "Percentage", "value": 2.0},
                "take_profit": {"type": "Percentage", "value": 5.0},
                "partial_take_profits": [
                    {"distance_pct": 3.0, "capital_pct": 50.0}
                ],
                "trailing_stop": {"active": True, "type": "Percentage", "buffer_pct": 0.3}
            }
        }),
    },
    {
        "id": "mock_strategy_3",
        "name": "EMA 9/20 Cross Long",
        "description": "Entrada larga al cruce de EMA9 sobre EMA20 con confirmación de volumen",
        "definition": json.dumps({
            "name": "EMA 9/20 Cross Long",
            "bias": "long",
            "entry_logic": {
                "timeframe": "1m",
                "root_condition": {
                    "type": "group",
                    "operator": "AND",
                    "conditions": [
                        {
                            "type": "indicator_comparison",
                            "source": {"name": "EMA", "period": 9},
                            "comparator": "CROSSES_ABOVE",
                            "target": {"name": "EMA", "period": 20},
                            "timeframe": "1m"
                        },
                        {
                            "type": "indicator_comparison",
                            "source": {"name": "Bar Close"},
                            "comparator": "GREATER_THAN",
                            "target": {"name": "VWAP"},
                            "timeframe": "1m"
                        }
                    ]
                }
            },
            "exit_logic": {
                "timeframe": "1m",
                "root_condition": {
                    "type": "group",
                    "operator": "AND",
                    "conditions": []
                }
            },
            "risk_management": {
                "use_hard_stop": True,
                "use_take_profit": True,
                "take_profit_mode": "Partial",
                "accept_reentries": True,
                "hard_stop": {"type": "ATR Multiplier", "value": 2.0},
                "take_profit": {"type": "Percentage", "value": 8.0},
                "partial_take_profits": [
                    {"distance_pct": 3.0, "capital_pct": 30.0},
                    {"distance_pct": 5.0, "capital_pct": 30.0},
                    {"distance_pct": 8.0, "capital_pct": 40.0}
                ],
                "trailing_stop": {"active": True, "type": "Percentage", "buffer_pct": 0.5}
            }
        }),
    },
]


def seed_mock_data():
    """Insert mock datasets and strategies into users.duckdb if tables are empty."""
    from app.database import get_user_db_connection, get_user_db_lock

    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            # Check if data already exists
            existing_datasets = con.execute("SELECT COUNT(*) FROM saved_queries").fetchone()[0]
            existing_strategies = con.execute("SELECT COUNT(*) FROM strategies").fetchone()[0]

            if existing_datasets == 0:
                now = datetime.now().isoformat()
                for ds in MOCK_DATASETS:
                    con.execute(
                        "INSERT INTO saved_queries (id, name, filters, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        [ds["id"], ds["name"], ds["filters"], now, now],
                    )
                print(f"[SEED] Inserted {len(MOCK_DATASETS)} mock datasets into users.duckdb")
            else:
                print(f"[SEED] Datasets already exist ({existing_datasets} rows), skipping seed")

            if existing_strategies == 0:
                now = datetime.now().isoformat()
                for st in MOCK_STRATEGIES:
                    con.execute(
                        "INSERT INTO strategies (id, name, description, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        [st["id"], st["name"], st["description"], st["definition"], now, now],
                    )
                print(f"[SEED] Inserted {len(MOCK_STRATEGIES)} mock strategies into users.duckdb")
            else:
                print(f"[SEED] Strategies already exist ({existing_strategies} rows), skipping seed")

        except Exception as e:
            print(f"[SEED ERROR] Could not seed mock data: {e}")
        finally:
            con.close()


if __name__ == "__main__":
    seed_mock_data()
