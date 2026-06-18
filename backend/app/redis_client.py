import os
from typing import Optional

# Optional dependency: if the redis package isn't installed the whole cache
# layer degrades to a no-op instead of crashing app startup on import.
try:
    import redis
except Exception:  # pragma: no cover
    redis = None

_redis_client = None


def get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    if redis is None:
        return None

    url = os.getenv("REDIS_URL", "")
    if not url:
        return None

    try:
        _redis_client = redis.from_url(url, decode_responses=True)
        _redis_client.ping()
        print("[REDIS] Connected successfully")
        return _redis_client
    except Exception as e:
        print(f"[REDIS] Connection failed: {e}")
        return None
