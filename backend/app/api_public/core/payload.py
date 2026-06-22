"""Payload rules (docs/b2d-gateway/01 §1.1): keep responses efficient by default.

- LTTB downsampling for equity/drawdown series (preserves visual peaks/valleys).
- Cursor pagination for the trades array.

These are why the API is efficient for remote, billed clients even though the
backend is the same as our own app's.
"""
from __future__ import annotations

import base64
from typing import Any, Optional

from app.api_public import config


# ── LTTB downsampling ────────────────────────────────────────────────────────
def lttb(points: list[dict], threshold: int) -> list[dict]:
    """Largest-Triangle-Three-Buckets downsampling of [{time, value}] series.

    Returns the original list unchanged when it already fits under `threshold`.
    Always keeps the first and last points.
    """
    n = len(points)
    if threshold <= 2 or threshold >= n:
        return points

    sampled = [points[0]]
    bucket_size = (n - 2) / (threshold - 2)
    a = 0  # index of the previously selected point

    for i in range(threshold - 2):
        # Average point of the next bucket.
        avg_start = int((i + 1) * bucket_size) + 1
        avg_end = min(int((i + 2) * bucket_size) + 1, n)
        count = max(avg_end - avg_start, 1)
        avg_x = avg_y = 0.0
        for j in range(avg_start, avg_end):
            avg_x += float(points[j]["time"])
            avg_y += float(points[j]["value"])
        avg_x /= count
        avg_y /= count

        # Current bucket range.
        range_from = int(i * bucket_size) + 1
        range_to = int((i + 1) * bucket_size) + 1
        ax = float(points[a]["time"])
        ay = float(points[a]["value"])

        max_area = -1.0
        next_a = range_from
        chosen = points[range_from]
        for j in range(range_from, range_to):
            px = float(points[j]["time"])
            py = float(points[j]["value"])
            area = abs((ax - avg_x) * (py - ay) - (ax - px) * (avg_y - ay)) * 0.5
            if area > max_area:
                max_area = area
                chosen = points[j]
                next_a = j
        sampled.append(chosen)
        a = next_a

    sampled.append(points[-1])
    return sampled


def downsample_series(points: Optional[list[dict]], max_points: Optional[int] = None) -> tuple[list[dict], bool]:
    """Return (series, was_downsampled)."""
    if not points:
        return points or [], False
    cap = max_points or config.EQUITY_DOWNSAMPLE_MAX_POINTS
    if len(points) <= cap:
        return points, False
    return lttb(points, cap), True


# ── Trades pagination ────────────────────────────────────────────────────────
def _encode_cursor(idx: int) -> str:
    return base64.urlsafe_b64encode(f"i:{idx}".encode()).decode()


def _decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        if raw.startswith("i:"):
            return max(0, int(raw[2:]))
    except Exception:
        pass
    return 0


def paginate_trades(
    trades: list[dict], limit: Optional[int] = None, cursor: Optional[str] = None
) -> dict:
    """Return {items, page} with an opaque next_cursor."""
    total = len(trades)
    lim = limit or config.TRADES_DEFAULT_LIMIT
    lim = max(1, min(lim, config.TRADES_MAX_LIMIT))
    start = _decode_cursor(cursor)
    end = min(start + lim, total)
    items = trades[start:end]
    next_cursor = _encode_cursor(end) if end < total else None
    return {
        "items": items,
        "page": {"limit": lim, "returned": len(items), "total": total, "next_cursor": next_cursor},
    }
