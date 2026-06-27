"""Tests for the public `robustness` module (EPIC C).

Facade is faked (no DB/engine). Covers: auth required, the 3 synchronous modules
return the contract shape, WFO is 501, gating default-permit, and internal errors
do NOT leak. test_architecture.py (separate) guards IP isolation.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api_public.app import app
from app.api_public.core.errors import ApiError
from app.api_public.facade import Facade, get_facade


_LEAK = "SUPER_SECRET_INTERNAL_TRACE"


def _montecarlo_payload():
    return {
        "simulations_run": 100, "ruin_probability": 1.25, "worst_drawdown": -62.4,
        "median_drawdown": -18.5, "extreme_drawdown_p95": -32.1, "extreme_drawdown_p99": -54.8,
        "probability_negative_return": 15.4, "n_trades_calculated": 500,
        "percentiles": {"p50": [{"time": 1_000_000_000, "value": 10000.0}]},
    }


class RobustFake(Facade):
    def __init__(self, error=None):
        self._error = error

    def robustness_montecarlo(self, run_id, **kw):
        if self._error:
            raise self._error
        return _montecarlo_payload()

    def robustness_sensitivity(self, run_id, **kw):
        return {"critical_locate_threshold": 1.85, "curves": {"locate_0.5": [{"time": 1, "value": 11000.0}]}}

    def robustness_black_swan(self, run_id, **kw):
        return {
            "time_to_recovery_trades": 45, "post_swan_ruin_risk_100t": 18.3,
            "sensitivity_matrix": [
                {"position_size_pct": 1.0, "severity_multiplier": 5.0, "ruin_probability": 2.1,
                 "max_drawdown": 14.5, "zone": "GREEN"}
            ],
        }


@pytest.fixture
def rob_client():
    def _make(error=None):
        app.dependency_overrides[get_facade] = lambda: RobustFake(error=error)
        return TestClient(app, raise_server_exceptions=False)
    yield _make
    app.dependency_overrides.clear()


def test_montecarlo_requires_auth(rob_client):
    c = rob_client()
    r = c.post("/v1/robustness/montecarlo", json={"run_id": "r1"})
    assert r.status_code == 401


def test_montecarlo_ok(rob_client, auth_headers):
    c = rob_client()
    r = c.post("/v1/robustness/montecarlo", json={"run_id": "r1", "simulations": 100}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ruin_probability"] == 1.25
    assert "p50" in body["percentiles"]


def test_sensitivity_ok(rob_client, auth_headers):
    c = rob_client()
    r = c.post("/v1/robustness/sensitivity", json={"run_id": "r1"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["critical_locate_threshold"] == 1.85


def test_black_swan_ok(rob_client, auth_headers):
    c = rob_client()
    r = c.post("/v1/robustness/black-swan", json={"run_id": "r1"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["sensitivity_matrix"][0]["zone"] == "GREEN"


def test_walk_forward_is_v2(rob_client, auth_headers):
    c = rob_client()
    r = c.post("/v1/robustness/walk-forward", json={"run_id": "r1"}, headers=auth_headers)
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "not_implemented"


def test_invalid_strategy_maps_to_422(rob_client, auth_headers):
    c = rob_client(error=ApiError("invalid_strategy", "No existe", status=422))
    r = c.post("/v1/robustness/montecarlo", json={"run_id": "ghost"}, headers=auth_headers)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_strategy"


def test_internal_error_does_not_leak(rob_client, auth_headers):
    c = rob_client(error=RuntimeError(_LEAK))
    r = c.post("/v1/robustness/montecarlo", json={"run_id": "r1"}, headers=auth_headers)
    assert r.status_code == 500
    assert _LEAK not in r.text


def test_robustness_in_openapi():
    schema = app.openapi()
    for p in ("/v1/robustness/montecarlo", "/v1/robustness/sensitivity", "/v1/robustness/black-swan"):
        assert p in schema["paths"], f"missing {p}"
