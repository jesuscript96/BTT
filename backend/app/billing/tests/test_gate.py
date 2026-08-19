"""Tests for the subscription gate (Fase 2E).

Verifies the two things that matter: (1) it is a strict NO-OP while dormant, so
product endpoints are unchanged in prod today; (2) once BILLING_ENABLED, it
enforces from the local tier (Locked -> 403, Pro -> pass).
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.billing import config
from app.billing import gate as gate_mod
from app.billing import store as store_mod
from app.billing.gate import subscription_gate
from app.billing.store import Store
from app.entitlements import policy


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "billing.sqlite"))
    store_mod.set_store(s)
    yield s
    store_mod.set_store(None)
    s.close()


def _client(feature: str) -> TestClient:
    app = FastAPI()

    @app.get("/x")
    def x(_g: bool = Depends(subscription_gate(feature))):
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


# ── Dormant = no-op ───────────────────────────────────────────────────────────
def test_gate_dormant_passes_even_anonymous(monkeypatch, store):
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    # Store has no record for anyone; dormant must still pass (no lookup at all).
    r = _client("backtester.run").get("/x")
    assert r.status_code == 200


def test_gate_dormant_does_not_resolve_identity(monkeypatch, store):
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    # If the gate touched identity while dormant it would call this; it must not.
    def _boom(auth):
        raise AssertionError("identity resolved while dormant")
    monkeypatch.setattr(gate_mod, "get_optional_user_id", _boom)
    assert _client("backtester.run").get("/x").status_code == 200


# ── Active = enforce ──────────────────────────────────────────────────────────
def test_gate_active_anonymous_is_403(monkeypatch, store):
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(gate_mod, "get_optional_user_id", lambda auth: None)
    assert _client("backtester.run").get("/x").status_code == 403


def test_gate_active_locked_user_is_403(monkeypatch, store):
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(gate_mod, "get_optional_user_id", lambda auth: "u_locked")
    # No grant, no subscription -> Locked.
    assert _client("backtester.run").get("/x").status_code == 403


def test_gate_active_pro_grant_passes(monkeypatch, store):
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(gate_mod, "get_optional_user_id", lambda auth: "u1")
    store.upsert_grant("u1", "Pro")  # perpetual comped
    assert _client("backtester.run").get("/x").status_code == 200


def test_gate_active_active_subscription_passes(monkeypatch, store):
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(gate_mod, "get_optional_user_id", lambda auth: "u1")
    store.upsert_customer("u1", "cus_1")
    store.upsert_subscription("sub_1", "u1", "cus_1", status="active")
    assert _client("backtester.run").get("/x").status_code == 200


# ── ticker.access fail-open for non-Locked, closed for Locked ─────────────────
def test_ticker_access_pro_passes_locked_blocked(monkeypatch, store):
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    # Pro (via grant) -> can(Pro,'ticker.access') defaults True.
    monkeypatch.setattr(gate_mod, "get_optional_user_id", lambda auth: "u1")
    store.upsert_grant("u1", "Pro")
    assert _client("ticker.access").get("/x").status_code == 200
    # Locked -> explicit False.
    monkeypatch.setattr(gate_mod, "get_optional_user_id", lambda auth: "u_locked")
    assert _client("ticker.access").get("/x").status_code == 403


# ── policy invariants for the new key ─────────────────────────────────────────
def test_policy_ticker_access_defaults():
    assert policy.can("Pro", "ticker.access") is True      # fail-open (no key)
    assert policy.can("Admin", "ticker.access") is True
    assert policy.can("Locked", "ticker.access") is False  # explicit close
