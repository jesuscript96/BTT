"""Configuration for the billing/subscription store (Fase 2A).

Isolated by design: this module holds NO Stripe secrets and NO monetization
policy. It only locates the dedicated SQLite store and exposes the master
dormancy flag. Stripe credentials arrive in a later phase (2C); the state->tier
mapping lives in entitlements/policy.py (2B). All values via env
(CODING_RULES.md), with technical defaults.

The store is a DEDICATED SQLite file, separate from BOTH:
  - users.duckdb — re-uploaded whole to GCS under a global lock on every write
    (memory btt-strategies-save-timeout); a per-webhook write there is inviable.
  - edgecute_api.sqlite — the public-API's own store.
See docs/FASE1_DISENO_TRIAL_SUSCRIPCION_STRIPE.md §2.
"""
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── Master dormancy flag ──────────────────────────────────────────────────────
# When False (default), billing is fully dormant: get_tier keeps its current
# Clerk-backed behavior and nothing here affects access. Consumed from Fase 2B
# onward; the store itself (this phase) is inert until a caller uses it.
BILLING_ENABLED = os.getenv("BILLING_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# ── Admin allowlist ───────────────────────────────────────────────────────────
# Comma-separated Clerk user_ids that bypass Stripe entirely (internal team,
# decision #1): always tier "Admin", no card, no trial. Single source of truth —
# both get_tier (middleware) and the /me summary (service) resolve admins here,
# so an admin never sees the card gate.
def billing_admin_ids() -> frozenset:
    raw = os.getenv("BILLING_ADMIN_USER_IDS", "")
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


# ── Store ─────────────────────────────────────────────────────────────────────
# Dedicated SQLite file. In prod it MUST sit on a persistent volume (or be
# GCS-synced); if lost, it is reconstructible from Stripe (reconciliation job,
# Fase 2D). Default lands in the CWD for local/dev, like edgecute_api.sqlite.
BILLING_DB_PATH = os.getenv(
    "EDGECUTE_BILLING_DB_PATH", os.path.join(os.getcwd(), "edgecute_billing.sqlite")
)

# ── Trial windows (days) ──────────────────────────────────────────────────────
# New sign-ups: Stripe Checkout trial, card mandatory (Fase 2C). Migrated users:
# a local grant window shown in-app, no card to start (Fase 2G). Both 7 days by
# decision (docs Fase 1 #5/#7). Consumed later; declared here as the single
# source of the windows.
BILLING_TRIAL_DAYS = _int("BILLING_TRIAL_DAYS", 7)
BILLING_MIGRATION_TRIAL_DAYS = _int("BILLING_MIGRATION_TRIAL_DAYS", 7)

# ── Stripe (Fase 2C) ──────────────────────────────────────────────────────────
# All EMPTY by default so billing stays dormant: the router is only mounted when
# BILLING_ENABLED (main.py), and the Stripe gateway is only constructed on
# demand and raises cleanly without a key. Use Stripe TEST keys until go-live
# (Fase 2G). Single monthly EUR Price by decision (#7).
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")  # frontend (2F)
STRIPE_PRICE_ID_MONTHLY_EUR = os.getenv("STRIPE_PRICE_ID_MONTHLY_EUR", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")    # verified in 2D

# Return URLs for Checkout success/cancel and the Billing Portal. Filled per
# environment; the request body may override them (frontend, 2F).
BILLING_SUCCESS_URL = os.getenv("BILLING_SUCCESS_URL", "")
BILLING_CANCEL_URL = os.getenv("BILLING_CANCEL_URL", "")
BILLING_PORTAL_RETURN_URL = os.getenv("BILLING_PORTAL_RETURN_URL", "")

# ── Plan display (Fase 2F) ────────────────────────────────────────────────────
# Cosmetic fallback for the billing UI when there is no invoice yet (e.g. during
# trial). The authoritative amount is always the Stripe invoice; this is only the
# label/price shown up front. 29€/mes by decision (#7).
BILLING_PLAN_LABEL = os.getenv("BILLING_PLAN_LABEL", "Pro")
BILLING_PLAN_AMOUNT_CENTS = _int("BILLING_PLAN_AMOUNT_CENTS", 2900)
BILLING_PLAN_CURRENCY = os.getenv("BILLING_PLAN_CURRENCY", "eur")
BILLING_PLAN_INTERVAL = os.getenv("BILLING_PLAN_INTERVAL", "month")
