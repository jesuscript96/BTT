"""Unit tests for the cross-cutting core: payload rules, rate limiting, store."""
from __future__ import annotations

import pytest

from app.api_public.core import payload, ratelimit
from app.api_public.core.errors import ApiError
from app.api_public.core.store import Store


# ── LTTB downsampling ────────────────────────────────────────────────────────
def test_lttb_noop_when_under_threshold():
    pts = [{"time": i, "value": i} for i in range(10)]
    out, down = payload.downsample_series(pts, max_points=100)
    assert down is False
    assert out == pts


def test_lttb_downsamples_and_keeps_endpoints():
    pts = [{"time": i, "value": (i % 7)} for i in range(5000)]
    out, down = payload.downsample_series(pts, max_points=500)
    assert down is True
    assert len(out) == 500
    assert out[0] == pts[0]
    assert out[-1] == pts[-1]


# ── Trades pagination ────────────────────────────────────────────────────────
def test_pagination_first_page_and_cursor():
    trades = [{"i": i} for i in range(1200)]
    page1 = payload.paginate_trades(trades, limit=500)
    assert page1["page"]["returned"] == 500
    assert page1["page"]["total"] == 1200
    cur = page1["page"]["next_cursor"]
    assert cur

    page2 = payload.paginate_trades(trades, limit=500, cursor=cur)
    assert page2["items"][0]["i"] == 500
    cur2 = page2["page"]["next_cursor"]
    page3 = payload.paginate_trades(trades, limit=500, cursor=cur2)
    assert page3["items"][0]["i"] == 1000
    assert page3["page"]["next_cursor"] is None  # last page


def test_pagination_limit_clamped():
    trades = [{"i": i} for i in range(10)]
    page = payload.paginate_trades(trades, limit=999999)
    assert page["page"]["limit"] <= 5000


# ── Rate limiter ─────────────────────────────────────────────────────────────
def test_rate_limiter_blocks_after_capacity():
    rl = ratelimit.RateLimiter()
    rl.check("k", rpm=2)
    rl.check("k", rpm=2)
    with pytest.raises(ApiError) as ei:
        rl.check("k", rpm=2)
    assert ei.value.code == "rate_limited"
    assert ei.value.status == 429


def test_rate_limiter_independent_keys():
    rl = ratelimit.RateLimiter()
    rl.check("a", rpm=1)
    rl.check("b", rpm=1)  # different key, fresh bucket


# ── Store ────────────────────────────────────────────────────────────────────
def test_store_api_key_roundtrip(tmp_path):
    s = Store(str(tmp_path / "s.sqlite"))
    token, row = s.create_api_key(owner_id="u1")
    assert token.startswith("ek_live_")
    got = s.get_key_by_token(token)
    assert got is not None and got.id == row.id and got.status == "active"
    # Wrong token does not resolve.
    assert s.get_key_by_token("ek_live_nope") is None
    # Revocation.
    s.revoke_key(row.id)
    assert s.get_key_by_token(token).status == "revoked"
    s.close()


def test_store_test_key_prefix(tmp_path):
    s = Store(str(tmp_path / "s.sqlite"))
    token, _ = s.create_api_key(test=True)
    assert token.startswith("ek_test_")
    s.close()


def test_store_usage_ledger(tmp_path):
    s = Store(str(tmp_path / "s.sqlite"))
    _, row = s.create_api_key()
    s.record_usage(row.id, "backtest", "run", ticker_days=120, trades=8)
    s.record_usage(row.id, "backtest", "run", ticker_days=80, trades=2)
    usage = s.usage_since(row.id, 0)
    assert usage["runs"] == 2
    assert usage["ticker_days"] == 200
    assert usage["trades"] == 10
    s.close()


def test_store_result_scoped_by_key(tmp_path):
    s = Store(str(tmp_path / "s.sqlite"))
    s.save_result("bt_1", "keyA", "succeeded", {"x": 1}, {"m": 2})
    assert s.get_result("bt_1", "keyA")["raw"] == {"x": 1}
    # A different key cannot read it.
    assert s.get_result("bt_1", "keyB") is None
    s.close()
