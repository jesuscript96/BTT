"""Security guard for get_optional_user_email (Fase 3, comped-by-email).

The verified-email rule is the door that keeps a bearer from claiming a
colleague's courtesy email via an UNVERIFIED address. These tests lock it.
We monkeypatch verify_clerk_token so no real JWT/JWKS is needed.
"""
from __future__ import annotations

from app.auth import clerk


def _mock_claims(monkeypatch, claims):
    monkeypatch.setattr(clerk, "AUTH_ENABLED", True)
    monkeypatch.setattr(clerk, "verify_clerk_token", lambda _t: claims)


def test_verified_email_is_honored_and_normalized(monkeypatch):
    _mock_claims(monkeypatch, {"sub": "u1", "email": "  Alice@B.com ", "email_verified": True})
    assert clerk.get_optional_user_email("Bearer x") == "alice@b.com"


def test_string_true_is_accepted(monkeypatch):
    # JWT templates often stringify booleans.
    _mock_claims(monkeypatch, {"email": "a@b.com", "email_verified": "true"})
    assert clerk.get_optional_user_email("Bearer x") == "a@b.com"


def test_unverified_email_is_rejected(monkeypatch):
    _mock_claims(monkeypatch, {"email": "a@b.com", "email_verified": False})
    assert clerk.get_optional_user_email("Bearer x") is None


def test_missing_verified_claim_is_rejected(monkeypatch):
    # If the JWT template omits email_verified → fail closed.
    _mock_claims(monkeypatch, {"email": "a@b.com"})
    assert clerk.get_optional_user_email("Bearer x") is None


def test_missing_email_returns_none(monkeypatch):
    _mock_claims(monkeypatch, {"email_verified": True})
    assert clerk.get_optional_user_email("Bearer x") is None


def test_auth_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(clerk, "AUTH_ENABLED", False)
    assert clerk.get_optional_user_email("Bearer x") is None


def test_no_bearer_returns_none(monkeypatch):
    monkeypatch.setattr(clerk, "AUTH_ENABLED", True)
    assert clerk.get_optional_user_email(None) is None
