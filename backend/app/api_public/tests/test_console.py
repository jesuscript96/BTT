"""Tests for the developer console (control plane). Clerk is stubbed so the owner
is deterministic and we can exercise owner-scoping."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import api_console
from app.api_public import config as cfg


@pytest.fixture
def owner():
    return {"id": "owner_A"}


@pytest.fixture
def capp(store, owner, monkeypatch):
    # Stub Clerk: the console owner is whatever owner["id"] currently holds.
    monkeypatch.setattr(api_console, "get_current_user_id", lambda authorization=None: owner["id"])
    app = FastAPI()
    app.include_router(api_console.router)
    return TestClient(app, raise_server_exceptions=False)


def test_overview_empty(capp):
    r = capp.get("/api/console/overview")
    assert r.status_code == 200
    b = r.json()
    assert b["owner_id"] == "owner_A"
    assert b["keys"]["total"] == 0
    assert b["plan"]["price"] is None
    assert any(s["id"] == "create_key" and s["done"] is False for s in b["onboarding"])


def test_create_list_revoke_key(capp):
    c = capp.post("/api/console/keys", json={"label": "ci key", "test": True})
    assert c.status_code == 200
    body = c.json()
    assert body["token"].startswith("ek_test_")
    assert body["token_shown_once"] is True
    assert body["key"]["label"] == "ci key"
    kid = body["key"]["id"]

    listed = capp.get("/api/console/keys").json()["keys"]
    assert len(listed) == 1
    # Never expose secrets.
    assert "token" not in listed[0]
    assert "key_hash" not in listed[0]
    assert listed[0]["prefix"].startswith("ek_test_")

    rv = capp.post(f"/api/console/keys/{kid}/revoke")
    assert rv.status_code == 200
    assert capp.get("/api/console/keys").json()["keys"][0]["status"] == "revoked"


def test_revoke_unknown_is_404(capp):
    assert capp.post("/api/console/keys/key_nope/revoke").status_code == 404


def test_keys_are_owner_scoped(capp, owner):
    owner["id"] = "owner_A"
    a = capp.post("/api/console/keys", json={}).json()["key"]["id"]
    owner["id"] = "owner_B"
    capp.post("/api/console/keys", json={})
    # owner_B sees only their own key, not A's.
    b_keys = capp.get("/api/console/keys").json()["keys"]
    assert all(k["id"] != a for k in b_keys)
    assert len(b_keys) == 1
    # owner_B cannot revoke A's key -> 404.
    assert capp.post(f"/api/console/keys/{a}/revoke").status_code == 404


def test_max_keys_per_owner(capp, monkeypatch):
    monkeypatch.setattr(cfg, "MAX_KEYS_PER_OWNER", 1)
    assert capp.post("/api/console/keys", json={}).status_code == 200
    assert capp.post("/api/console/keys", json={}).status_code == 409


def test_usage_and_billing(capp, store):
    kid = capp.post("/api/console/keys", json={}).json()["key"]["id"]
    store.record_usage(kid, "backtest", "run", ticker_days=120, trades=5)
    u = capp.get("/api/console/usage").json()
    assert u["all_time"]["ticker_days"] == 120
    assert u["all_time"]["trades"] == 5
    assert len(u["activity"]) == 1

    b = capp.get("/api/console/billing").json()
    assert b["stripe"]["connected"] is False
    assert b["plan"]["price"] is None
    assert b["invoices"] == []


def test_overview_reflects_usage(capp, store):
    kid = capp.post("/api/console/keys", json={}).json()["key"]["id"]
    store.record_usage(kid, "backtest", "run", ticker_days=50, trades=2)
    ov = capp.get("/api/console/overview").json()
    assert ov["usage_period"]["ticker_days"] == 50
    assert any(s["id"] == "first_backtest" and s["done"] is True for s in ov["onboarding"])


def test_playground_indicators_and_validate(capp):
    ind = capp.get("/api/console/playground/indicators?category=Momentum").json()
    assert ind["indicators"] and all(e["category"] == "Momentum" for e in ind["indicators"])

    val = capp.post(
        "/api/console/playground/validate", json={"strategy": {"name": "x", "bias": "sideways"}}
    ).json()
    assert val["valid"] is False
    assert any("bias" in e["path"] for e in val["errors"])
