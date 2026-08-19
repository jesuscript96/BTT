"""Unit tests for resolve_tier + the Locked policy tier (Fase 2B).

Pure/isolated: a temp store, no Stripe, no Clerk, no HTTP. get_tier is NOT
exercised here — it still reads Clerk and is untouched in this phase.
"""
from __future__ import annotations

import pytest

from app.billing.store import Store
from app.billing.tier_resolver import resolve_tier, TIER_ADMIN, TIER_PRO, TIER_LOCKED
from app.entitlements import policy

NOW = 1_000_000_000.0
FUTURE = NOW + 10_000.0
PAST = NOW - 10_000.0


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "billing.sqlite"))
    yield s
    s.close()


def _resolve(store, user_id, now=NOW):
    return resolve_tier(user_id, now=now, store=store)


# ── Fail-closed defaults ──────────────────────────────────────────────────────
def test_no_user_is_locked(store):
    assert _resolve(store, None) == TIER_LOCKED


def test_unknown_user_is_locked(store):
    assert _resolve(store, "ghost") == TIER_LOCKED


# ── Grants ────────────────────────────────────────────────────────────────────
def test_admin_grant_resolves_admin(store):
    store.upsert_grant("u1", "Admin", reason="internal")  # perpetual
    assert _resolve(store, "u1") == TIER_ADMIN


def test_pro_grant_active_resolves_pro(store):
    store.upsert_grant("u1", "Pro", reason="migration-trial", expires_at=FUTURE)
    assert _resolve(store, "u1") == TIER_PRO


def test_pro_grant_expired_falls_through_to_locked(store):
    store.upsert_grant("u1", "Pro", reason="migration-trial", expires_at=PAST)
    # Expired migration trial, no subscription -> paywall.
    assert _resolve(store, "u1") == TIER_LOCKED


def test_expired_pro_grant_falls_through_to_active_subscription(store):
    store.upsert_grant("u1", "Pro", reason="migration-trial", expires_at=PAST)
    store.upsert_subscription("sub_1", "u1", "cus_1", status="active")
    # Grant expired but the user then subscribed -> Pro from the subscription.
    assert _resolve(store, "u1") == TIER_PRO


def test_admin_grant_beats_canceled_subscription(store):
    store.upsert_grant("u1", "Admin")
    store.upsert_subscription("sub_1", "u1", "cus_1", status="canceled")
    assert _resolve(store, "u1") == TIER_ADMIN


def test_unknown_grant_tier_is_not_trusted(store):
    store.upsert_grant("u1", "Wizard")  # not a real access tier
    assert _resolve(store, "u1") == TIER_LOCKED


# ── Subscription status mapping (§3 table) ────────────────────────────────────
@pytest.mark.parametrize("status", ["trialing", "active", "past_due"])
def test_access_statuses_resolve_pro(store, status):
    store.upsert_subscription("sub_1", "u1", "cus_1", status=status)
    assert _resolve(store, "u1") == TIER_PRO


@pytest.mark.parametrize(
    "status", ["canceled", "unpaid", "incomplete", "incomplete_expired", "weird_unknown"]
)
def test_non_access_statuses_resolve_locked(store, status):
    store.upsert_subscription("sub_1", "u1", "cus_1", status=status)
    assert _resolve(store, "u1") == TIER_LOCKED


def test_latest_subscription_wins(store):
    # Old active sub, then a newer canceled one -> latest (canceled) drives state.
    store.upsert_subscription("sub_old", "u1", "cus_1", status="active")
    import time as _t; _t.sleep(0.01)
    store.upsert_subscription("sub_new", "u1", "cus_1", status="canceled")
    assert _resolve(store, "u1") == TIER_LOCKED


# ── The Locked policy tier itself ─────────────────────────────────────────────
def test_locked_tier_exists_and_closes_everything():
    assert "Locked" in policy.POLICY
    for feature, kind in policy.FEATURE_TYPES.items():
        if kind == "boolean":
            assert policy.can("Locked", feature) is False, f"{feature} should be closed"
        else:  # limit
            assert policy.limit("Locked", feature) == 0, f"{feature} should be 0"


def test_locked_covers_full_feature_catalog():
    # Locked must define every feature key (no accidental fall-through to allow).
    assert set(policy.POLICY["Locked"].keys()) == set(policy.FEATURE_TYPES.keys())


def test_default_tier_unchanged_in_this_phase():
    # 2B must NOT flip the default; that is the 2G cutover.
    assert policy.DEFAULT_TIER == "Beta"
