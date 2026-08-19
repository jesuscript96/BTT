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
