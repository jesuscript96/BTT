"""In-process per-key rate limiting (token bucket). Redis = v2 (only needed for
multi-instance). Fixed-window-free token bucket keeps it simple and correct for a
single instance.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.api_public.core.auth import Principal
from app.api_public.core.errors import ApiError


@dataclass
class _Bucket:
    tokens: float
    last: float


class RateLimiter:
    def __init__(self):
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str, rpm: int) -> None:
        """Consume one token. Raise ApiError(429) when the bucket is empty.

        Capacity = rpm, refill = rpm tokens per 60s.
        """
        if rpm <= 0:
            return
        now = time.monotonic()
        refill_per_sec = rpm / 60.0
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=float(rpm), last=now)
                self._buckets[key] = b
            # Refill since last check.
            elapsed = now - b.last
            b.tokens = min(float(rpm), b.tokens + elapsed * refill_per_sec)
            b.last = now
            if b.tokens < 1.0:
                retry_after = max(1, int((1.0 - b.tokens) / refill_per_sec) + 1)
                raise ApiError(
                    "rate_limited",
                    "Límite de peticiones superado.",
                    details={"retry_after_seconds": retry_after},
                )
            b.tokens -= 1.0

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_limiter = RateLimiter()


def enforce(principal: Principal) -> None:
    _limiter.check(principal.api_key_id, principal.rate_limit_rpm)


def reset_limiter() -> None:
    _limiter.reset()
