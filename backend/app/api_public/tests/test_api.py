"""End-to-end tests of the API surface (facade faked, no engine/data)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api_public import config
from app.api_public.app import app
from app.api_public.core import gating
from app.api_public.facade import get_facade
from app.api_public.tests.conftest import FakeFacade


VALID_STRATEGY = {
    "name": "VWAP fade short",
    "bias": "short",
    "apply_day": "gap_day",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group", "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "CROSSES_BELOW",
                    "target": {"name": "VWAP"},
                }
            ],
        },
    },
    "risk_management": {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 3.0}},
}


def make_body(dataset_ref="ds_123", include=None, **execution):
    return {
        "universe": {"dataset_ref": dataset_ref, "date_from": "2024-01-01", "date_to": "2024-01-31"},
        "strategy": VALID_STRATEGY,
        "execution": {"init_cash": 10000, "market_sessions": ["RTH"], **execution},
        "include": include or ["metrics", "equity", "days"],
    }


# ── Health & auth ────────────────────────────────────────────────────────────
def test_health_no_auth(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_missing_key(client):
    r = client.get("/v1/catalog/indicators")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_auth_bad_format(client):
    r = client.get("/v1/catalog/indicators", headers={"Authorization": "Bearer not_a_key"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_auth_revoked(client, store):
    token, row = store.create_api_key()
    store.revoke_key(row.id)
    r = client.get("/v1/catalog/indicators", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


# ── Catalog ──────────────────────────────────────────────────────────────────
def test_catalog_lists_indicators(client, auth_headers):
    r = client.get("/v1/catalog/indicators", headers=auth_headers)
    assert r.status_code == 200
    names = {e["name"] for e in r.json()["indicators"]}
    assert {"VWAP", "RSI", "PM High", "Bar Close"} <= names


def test_catalog_category_filter(client, auth_headers):
    r = client.get("/v1/catalog/indicators?category=Momentum", headers=auth_headers)
    assert r.status_code == 200
    cats = {e["category"] for e in r.json()["indicators"]}
    assert cats == {"Momentum"}


# ── Strategy validation ──────────────────────────────────────────────────────
def test_validate_valid_strategy(client, auth_headers):
    r = client.post("/v1/strategies/validate", json=VALID_STRATEGY, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"valid": True, "errors": []}


def test_validate_invalid_strategy(client, auth_headers):
    bad = {"name": "x", "bias": "sideways"}  # bad bias + missing required blocks
    r = client.post("/v1/strategies/validate", json=bad, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    paths = {e["path"] for e in body["errors"]}
    assert any("bias" in p for p in paths)
    assert any("entry_logic" in p for p in paths)


# ── Universe preview ─────────────────────────────────────────────────────────
def test_universe_preview(client, auth_headers):
    r = client.post("/v1/universe/preview", json={"dataset_ref": "ds_123",
                    "date_from": "2024-01-01", "date_to": "2024-01-31"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ticker_days"] == 10 and body["within_cap"] is True


def test_universe_preview_filters_is_v2(client, auth_headers):
    r = client.post("/v1/universe/preview", json={"filters": {"min_price": 1}}, headers=auth_headers)
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "not_implemented"


# ── Run backtest (sync) ──────────────────────────────────────────────────────
def test_run_backtest_default_include(client, auth_headers):
    r = client.post("/v1/backtests", json=make_body(), headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["result"]["aggregate_metrics"]["total_trades"] == 3
    assert body["result"]["global_equity"]  # equity included
    assert body["result"].get("trades") is None  # trades NOT included by default
    assert body["meta"]["trades_total"] == 3


def test_run_backtest_include_trades_paginated(client, auth_headers):
    r = client.post("/v1/backtests", json=make_body(include=["metrics", "trades"]), headers=auth_headers)
    assert r.status_code == 200
    trades = r.json()["result"]["trades"]
    assert trades["page"]["total"] == 3
    assert len(trades["items"]) == 3


def test_run_backtest_missing_universe(client, auth_headers):
    body = make_body()
    body["universe"] = None
    r = client.post("/v1/backtests", json=body, headers=auth_headers)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_universe"


def test_run_backtest_universe_too_large(store, auth_headers):
    app.dependency_overrides[get_facade] = lambda: FakeFacade(ticker_days=10_000_000)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/v1/backtests", json=make_body(), headers=auth_headers)
    app.dependency_overrides.clear()
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "universe_too_large"
    assert r.json()["error"]["details"]["cap"] == config.MAX_TICKER_DAYS_PER_RUN


def test_run_backtest_mock_skips_cap(store, auth_headers):
    # mock dataset bypasses the preview/cap path entirely.
    app.dependency_overrides[get_facade] = lambda: FakeFacade(ticker_days=10_000_000)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/v1/backtests", json=make_body(dataset_ref="mock_dataset_1"), headers=auth_headers)
    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["meta"]["ticker_days"] == 0


# ── Retrieve / intraday / cancel ─────────────────────────────────────────────
def test_get_backtest_and_scoping(client, store, auth_headers):
    run = client.post("/v1/backtests", json=make_body(), headers=auth_headers)
    job_id = run.json()["job_id"]

    got = client.get(f"/v1/backtests/{job_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["result"]["aggregate_metrics"]["total_trades"] == 3

    # Unknown id -> 404.
    assert client.get("/v1/backtests/bt_nope", headers=auth_headers).status_code == 404

    # Another key cannot read it (scoping).
    other_token, _ = store.create_api_key(owner_id="user_2")
    other = client.get(f"/v1/backtests/{job_id}", headers={"Authorization": f"Bearer {other_token}"})
    assert other.status_code == 404


def test_intraday_series(client, auth_headers):
    run = client.post("/v1/backtests", json=make_body(), headers=auth_headers)
    job_id = run.json()["job_id"]
    ok = client.get(f"/v1/backtests/{job_id}/intraday?ticker=AAPL&date=2024-01-02", headers=auth_headers)
    assert ok.status_code == 200
    assert ok.json()["ticker"] == "AAPL" and len(ok.json()["equity"]) == 10
    # Missing series -> 404.
    miss = client.get(f"/v1/backtests/{job_id}/intraday?ticker=ZZZZ&date=2024-01-02", headers=auth_headers)
    assert miss.status_code == 404


def test_cancel_finished_job_conflict(client, auth_headers):
    run = client.post("/v1/backtests", json=make_body(), headers=auth_headers)
    job_id = run.json()["job_id"]
    r = client.post(f"/v1/backtests/{job_id}/cancel", headers=auth_headers)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


# ── Metering ─────────────────────────────────────────────────────────────────
def test_metering_records_usage(client, store, auth_headers):
    client.post("/v1/backtests", json=make_body(), headers=auth_headers)
    # Find the api key id for user_1.
    row = store.get_key_by_token(auth_headers["Authorization"].split(" ", 1)[1])
    usage = store.usage_since(row.id, 0)
    assert usage["runs"] == 1
    assert usage["ticker_days"] == 10
    assert usage["trades"] == 3


# ── Gating hook (mechanism present, default allow, overrideable) ──────────────
def test_gating_default_allows(client, auth_headers):
    assert client.get("/v1/catalog/indicators", headers=auth_headers).status_code == 200


def test_gating_policy_can_deny(client, auth_headers):
    gating.set_policy(lambda principal, module, action: False)
    try:
        r = client.get("/v1/catalog/indicators", headers=auth_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"
    finally:
        gating.set_policy(None)


# ── Rate limit at the endpoint ───────────────────────────────────────────────
def test_rate_limit_endpoint(client, auth_headers):
    config.DEFAULT_PLAN["rate_limit_rpm"] = 1
    try:
        a = client.get("/v1/catalog/indicators", headers=auth_headers)
        b = client.get("/v1/catalog/indicators", headers=auth_headers)
        assert a.status_code == 200
        assert b.status_code == 429
        assert b.json()["error"]["code"] == "rate_limited"
    finally:
        config.DEFAULT_PLAN["rate_limit_rpm"] = config.RATE_LIMIT_RPM


# ── Error isolation: no leak ─────────────────────────────────────────────────
def test_internal_error_does_not_leak(store, auth_headers):
    secret = "SUPER_SECRET_INTERNAL_xyz"
    app.dependency_overrides[get_facade] = lambda: FakeFacade(run_error=RuntimeError(secret))
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/v1/backtests", json=make_body(), headers=auth_headers)
    app.dependency_overrides.clear()
    assert r.status_code == 500
    text = r.text
    assert secret not in text
    assert "RuntimeError" not in text
    assert "Traceback" not in text
    assert r.json()["error"]["code"] == "internal_error"
    assert r.json()["error"]["request_id"].startswith("req_")
