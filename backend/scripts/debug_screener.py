
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import Request
from starlette.datastructures import QueryParams

# Setup
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from app.database import get_db_connection
from app.routers.market import screen_market

# Mock Request
class MockRequest:
    def __init__(self, params):
        self.query_params = QueryParams(params)

def debug_screener():
    print("Testing /api/market/screener...")
    try:
        req = MockRequest({})
        result = screen_market(
            request=req,
            limit=100
        )
        print("Success!")
        print("Records:", len(result['records']))
        print("Stats:", result['stats']['count'])
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_screener()
