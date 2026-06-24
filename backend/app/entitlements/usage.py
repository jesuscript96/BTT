"""
Usage counters for limit features, backed by Redis with automatic TTL.

Keys follow:  usage:{user_id}:{feature}:{window_bucket}
  - day   -> bucket YYYY-MM-DD, TTL 24h
  - month -> bucket YYYY-MM,    TTL 31d

Permissive fallback: if Redis is unavailable (not configured / down), reads
return 0 and increments are no-ops, so usage tracking NEVER blocks a request.
Only features listed in policy.LIMIT_WINDOWS are counted; everything else
returns 0.
"""
from datetime import datetime, timezone

from app.redis_client import get_redis
from app.entitlements import policy

_DAY_TTL = 24 * 60 * 60        # 24 hours
_MONTH_TTL = 31 * 24 * 60 * 60  # 31 days


def _window_for(feature: str):
    return policy.LIMIT_WINDOWS.get(feature)


def _bucket(window: str) -> str:
    now = datetime.now(timezone.utc)
    if window == "month":
        return now.strftime("%Y-%m")
    return now.strftime("%Y-%m-%d")  # default: day


def _ttl(window: str) -> int:
    return _MONTH_TTL if window == "month" else _DAY_TTL


def _key(user_id: str, feature: str, window: str) -> str:
    return f"usage:{user_id}:{feature}:{_bucket(window)}"


def get_usage(user_id: str, feature: str) -> int:
    """Current usage count for a windowed feature. 0 if untracked/unavailable."""
    window = _window_for(feature)
    if window is None or not user_id:
        return 0
    client = get_redis()
    if client is None:
        return 0  # permissive: no Redis -> don't block
    try:
        raw = client.get(_key(user_id, feature, window))
        return int(raw) if raw is not None else 0
    except Exception:
        return 0


def increment_usage(user_id: str, feature: str, amount: int = 1) -> int:
    """
    Increment and return the new count. Sets the TTL on first write in the
    window so the counter self-expires. No-op (returns 0) when untracked or
    Redis is unavailable.
    """
    window = _window_for(feature)
    if window is None or not user_id:
        return 0
    client = get_redis()
    if client is None:
        return 0  # permissive: no Redis -> don't block
    try:
        key = _key(user_id, feature, window)
        new_value = client.incrby(key, amount)
        if new_value == amount:
            # First increment in this window -> attach expiry.
            client.expire(key, _ttl(window))
        return int(new_value)
    except Exception:
        return 0
