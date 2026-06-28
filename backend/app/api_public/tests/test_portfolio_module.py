"""Commercial API — `portfolio` module: auth, gating, happy paths, OpenAPI.

Never touches the engine or a DB: the facade's portfolio methods are faked.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api_public.app import app
from app.api_public.facade import Facade, get_facade


class PortfolioFakeFacade(Facade):
    """Returns deterministic portfolio analytics with no DB / engine."""

    def portfolio_combine(self, owner_id, kwargs):
        return {
            "timestamps": [1, 2, 3],
            "combined_equity": [10000.0, 10050.0, 10100.0],
            "combined_drawdown": [0.0, 0.0, -0.5],
            "metrics": {"sharpe_ratio": 1.5, "max_drawdown_pct": -0.5, "n_days": 2},
            "weights": {bid: 1.0 / len(kwargs["backtest_ids"]) for bid in kwargs["backtest_ids"]},
        }

    def portfolio_montecarlo(self, owner_id, kwargs):
        return {
            "percentiles": {"p5": [10000.0], "p25": [10000.0], "p50": [10000.0],
                            "p75": [10000.0], "p95": [10000.0]},
            "var_95_pct": -2.5, "var_95_usd": -250.0,
            "var_99_pct": -4.0, "var_99_usd": -400.0,
            "cvar_95_pct": -3.5, "cvar_95_usd": -350.0,
            "cvar_99_pct": -5.0, "cvar_99_usd": -500.0,
            "ruin_probability": 1.2,
        }

    def portfolio_correlation(self, owner_id, kwargs):
        return {"labels": ["A", "B"], "pearson": [[1.0, 0.3], [0.3, 1.0]],
                "spearman": [[1.0, 0.25], [0.25, 1.0]]}

    def portfolio_allocation(self, owner_id, kwargs):
        ids = kwargs["backtest_ids"]
        return {
            "weights": {bid: 1.0 / len(ids) for bid in ids},
            "comparison_equity": [10000.0, 10100.0],
            "comparison_drawdown": [0.0, -0.2],
            "metrics": {"sharpe_ratio": 2.0, "n_days": 1},
        }


@pytest.fixture
def pf_client():
    app.dependency_overrides[get_facade] = lambda: PortfolioFakeFacade()
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()


def test_portfolio_module_is_mounted():
    schema = app.openapi()
    for p in ("/v1/portfolio/combine", "/v1/portfolio/montecarlo",
              "/v1/portfolio/correlation", "/v1/portfolio/allocation"):
        assert p in schema["paths"], f"missing {p}"


def test_combine_requires_auth(pf_client):
    r = pf_client.post("/v1/portfolio/combine", json={"backtest_ids": ["a"]})
    assert r.status_code == 401


def test_combine_happy_path(pf_client, auth_headers):
    r = pf_client.post("/v1/portfolio/combine",
                       json={"backtest_ids": ["a", "b"]}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["combined_equity"][0] == 10000.0
    assert set(body["weights"]) == {"a", "b"}


def test_montecarlo_happy_path(pf_client, auth_headers):
    r = pf_client.post("/v1/portfolio/montecarlo",
                       json={"backtest_ids": ["a", "b"], "weights": {"a": 0.5, "b": 0.5},
                             "simulations": 500}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["var_95_usd"] == -250.0


def test_correlation_requires_two(pf_client, auth_headers):
    r = pf_client.post("/v1/portfolio/correlation",
                       json={"backtest_ids": ["a"]}, headers=auth_headers)
    assert r.status_code == 422  # min_length=2 on the request model


def test_allocation_happy_path(pf_client, auth_headers):
    r = pf_client.post("/v1/portfolio/allocation",
                       json={"backtest_ids": ["a", "b"], "method": "hrp"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert sum(r.json()["weights"].values()) == pytest.approx(1.0)
