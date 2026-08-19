"""Tests for the get_tier cutover switch (Fase 2G).

get_tier is the single switch: dormant -> Clerk path (unchanged); BILLING_ENABLED
-> admin allowlist + resolve_tier(local store).
"""
from __future__ import annotations

import pytest

from app.billing import config as billing_config
from app.billing import store as store_mod
from app.billing.store import Store
from app.entitlements.middleware import get_tier


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store(str(tmp_path / "billing.sqlite"))
    store_mod.set_store(s)
    monkeypatch.delenv("DEV_TIER", raising=False)
    monkeypatch.delenv("BILLING_ADMIN_USER_IDS", raising=False)
    yield s
    store_mod.set_store(None)
    s.close()


def test_get_tier_dormant_is_unchanged(monkeypatch, store):
    monkeypatch.setattr(billing_config, "BILLING_ENABLED", False)
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    # Pre-billing behavior: no user -> DEFAULT_TIER (Beta).
    assert get_tier(None) == "Beta"


def test_get_tier_billing_anon_is_locked(monkeypatch, store):
    monkeypatch.setattr(billing_config, "BILLING_ENABLED", True)
    assert get_tier(None) == "Locked"


def test_get_tier_billing_pro_from_grant(monkeypatch, store):
    monkeypatch.setattr(billing_config, "BILLING_ENABLED", True)
    store.upsert_grant("u1", "Pro")
    assert get_tier("u1") == "Pro"


def test_get_tier_billing_pro_from_active_subscription(monkeypatch, store):
    monkeypatch.setattr(billing_config, "BILLING_ENABLED", True)
    store.upsert_customer("u1", "cus_1")
    store.upsert_subscription("sub_1", "u1", "cus_1", status="active")
    assert get_tier("u1") == "Pro"


def test_get_tier_billing_admin_allowlist(monkeypatch, store):
    monkeypatch.setattr(billing_config, "BILLING_ENABLED", True)
    monkeypatch.setenv("BILLING_ADMIN_USER_IDS", "u_admin, u2")
    assert get_tier("u_admin") == "Admin"
    assert get_tier("u2") == "Admin"
    assert get_tier("u_nobody") == "Locked"  # not on allowlist, no sub/grant


def test_dev_tier_still_wins_over_billing(monkeypatch, store):
    monkeypatch.setattr(billing_config, "BILLING_ENABLED", True)
    monkeypatch.setenv("DEV_TIER", "Pro")
    assert get_tier(None) == "Pro"
