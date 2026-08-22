"""Fase 3 — identity-by-email reconciliation (admins + comped + preferential trial).

Covers _reconcile_identity_email and _reconcile_trial_override_email (service.py),
which materialize/revoke grants keyed by user_id from the email allowlists so the
product gate (resolve_tier) and the /me summary both honor them. These are the
mechanism behind "admins/cortesía/preferenciales por email" (migration-proof: the
email survives a Clerk-instance change, the user_id doesn't).

No Stripe: the reconcile paths + get_billing_summary only touch the store, so a
dummy gateway is injected.
"""
from __future__ import annotations

import pytest

from app.billing.service import BillingService
from app.billing.store import Store


@pytest.fixture()
def store(tmp_path):
    s = Store(path=str(tmp_path / "billing_test.sqlite"))
    yield s
    s.close()


@pytest.fixture()
def svc(store):
    # gateway is never called by reconcile/get_billing_summary — inject a dummy.
    return BillingService(store=store, gateway=object())


U1 = "user_alice"
U2 = "user_alice_newid"  # same person, post-Clerk-migration user_id
ALICE = "Alice@Example.com"  # mixed case on purpose (normalization)
alice = "alice@example.com"


# ── Admin by email ───────────────────────────────────────────────────────────
def test_admin_email_materializes_admin_grant(store, svc):
    store.add_admin_email(ALICE, granted_by="adrian")
    summary = svc.get_billing_summary(U1, email=alice)
    assert summary["tier"] == "Admin"
    assert summary["stage"] == "admin"
    assert summary["access"] is True
    grant = store.get_grant(U1)
    assert grant is not None and grant.grant_tier == "Admin" and grant.reason == "admin"
    assert grant.expires_at is None  # perpetual


def test_admin_email_normalized(store, svc):
    store.add_admin_email("BOB@X.COM")
    # user presents the lowercased verified email — must still match.
    summary = svc.get_billing_summary("user_bob", email="bob@x.com")
    assert summary["tier"] == "Admin"


# ── Comped by email ──────────────────────────────────────────────────────────
def test_comped_email_materializes_pro_grant(store, svc):
    store.add_comped_email(alice)
    summary = svc.get_billing_summary(U1, email=alice)
    assert summary["tier"] == "Pro"
    assert summary["stage"] == "comped"
    grant = store.get_grant(U1)
    assert grant is not None and grant.grant_tier == "Pro" and grant.reason == "comped"


# ── Precedence: admin wins over comped ───────────────────────────────────────
def test_admin_wins_over_comped(store, svc):
    store.add_comped_email(alice)
    store.add_admin_email(alice)
    summary = svc.get_billing_summary(U1, email=alice)
    assert summary["tier"] == "Admin"
    assert store.get_grant(U1).reason == "admin"


def test_comped_then_promoted_to_admin(store, svc):
    store.add_comped_email(alice)
    assert svc.get_billing_summary(U1, email=alice)["tier"] == "Pro"
    # Promote: add to admin list; next /me upgrades the single grant row.
    store.add_admin_email(alice)
    summary = svc.get_billing_summary(U1, email=alice)
    assert summary["tier"] == "Admin"
    assert store.get_grant(U1).reason == "admin"


def test_admin_then_demoted_to_comped(store, svc):
    store.add_admin_email(alice)
    assert svc.get_billing_summary(U1, email=alice)["tier"] == "Admin"
    store.remove_admin_email(alice)
    store.add_comped_email(alice)
    summary = svc.get_billing_summary(U1, email=alice)
    assert summary["tier"] == "Pro"
    assert store.get_grant(U1).reason == "comped"


# ── Revocation ───────────────────────────────────────────────────────────────
def test_removal_revokes_on_next_me(store, svc):
    store.add_comped_email(alice)
    assert svc.get_billing_summary(U1, email=alice)["access"] is True
    store.remove_comped_email(alice)
    summary = svc.get_billing_summary(U1, email=alice)
    assert summary["tier"] == "Locked"
    assert summary["access"] is False
    assert store.get_grant(U1) is None


def test_reconcile_does_not_touch_non_identity_grant(store, svc):
    # A migration-trial Pro grant (reason != admin/comped) must survive reconcile
    # even when the email is on no list.
    store.upsert_grant(U1, "Pro", reason="migration_trial", expires_at=None)
    svc.get_billing_summary(U1, email="nobody@x.com")
    grant = store.get_grant(U1)
    assert grant is not None and grant.reason == "migration_trial"


def test_no_email_is_noop(store, svc):
    # Without a trusted email we must neither grant nor revoke.
    store.add_admin_email(alice)  # listed, but we can't verify the caller
    summary = svc.get_billing_summary(U1, email=None)
    assert store.get_grant(U1) is None
    assert summary["tier"] == "Locked"


# ── Idempotency: no store churn on repeated /me ──────────────────────────────
def test_repeated_me_does_not_rewrite_grant(store, svc):
    store.add_admin_email(alice)
    svc.get_billing_summary(U1, email=alice)
    g1 = store.get_grant(U1)
    svc.get_billing_summary(U1, email=alice)
    g2 = store.get_grant(U1)
    assert g1.created_at == g2.created_at  # not re-inserted


# ── Preferential trial by email ──────────────────────────────────────────────
def test_preferential_email_seeds_override_once(store, svc):
    store.add_trial_override_email(alice, 14, granted_by="adrian")
    svc.get_billing_summary(U1, email=alice)
    ov = store.get_trial_override(U1)
    assert ov is not None and ov.days == 14 and ov.consumed_at is None


def test_preferential_not_rearmed_after_consume(store, svc):
    store.add_trial_override_email(alice, 14)
    svc.get_billing_summary(U1, email=alice)
    # Simulate Checkout consuming the one-shot.
    assert store.consume_trial_override(U1) == 14
    assert store.get_trial_override(U1).consumed_at is not None
    # A later login must NOT re-arm it (no recycling of the preferential trial).
    svc.get_billing_summary(U1, email=alice)
    assert store.get_trial_override(U1).consumed_at is not None


def test_preferential_migration_proof_new_user_id(store, svc):
    # Same email, brand-new user_id (post Clerk prod migration) → seeds fresh.
    store.add_trial_override_email(alice, 14)
    svc.get_billing_summary(U2, email=alice)
    ov = store.get_trial_override(U2)
    assert ov is not None and ov.days == 14 and ov.consumed_at is None


def test_preferential_rejects_bad_days(store):
    with pytest.raises(ValueError):
        store.add_trial_override_email(alice, 99)
    with pytest.raises(ValueError):
        store.add_trial_override_email(alice, 0)


# ── Store-level list helpers ─────────────────────────────────────────────────
def test_admin_email_list_and_remove(store):
    store.add_admin_email("a@x.com")
    store.add_admin_email("b@x.com")
    assert set(store.list_admin_emails()) == {"a@x.com", "b@x.com"}
    assert store.has_admin_email("A@X.COM") is True
    store.remove_admin_email("a@x.com")
    assert store.has_admin_email("a@x.com") is False


def test_trial_override_email_list(store):
    store.add_trial_override_email("a@x.com", 14)
    store.add_trial_override_email("b@x.com", 7)
    got = dict(store.list_trial_override_emails())
    assert got == {"a@x.com": 14, "b@x.com": 7}
