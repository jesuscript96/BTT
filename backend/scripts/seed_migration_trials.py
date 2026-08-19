"""Seed migration trial grants for existing users (Fase 2G cutover, step 1).

Grants every existing user a 7-day in-app trial (entitlement_grants,
grant_tier='Pro', reason='migration-trial', expires_at=now+N days) so that when
DEFAULT_TIER flips to 'Locked' and BILLING_ENABLED turns on, current users are
NOT locked out — they keep access for N days and see the in-app countdown
(decision Jesús #5). At expiry -> Locked -> Checkout (direct charge, no Stripe
trial).

MUST run BEFORE flipping DEFAULT_TIER / BILLING_ENABLED (strict order, docs
FASE1 §7). Idempotent: users who already have a grant are skipped, so re-running
never shortens or resets an existing trial.

Usage (from backend/):
    python -m scripts.seed_migration_trials --dry-run          # preview only
    python -m scripts.seed_migration_trials                    # seed from Clerk
    python -m scripts.seed_migration_trials --user-ids u1,u2   # explicit list
    python -m scripts.seed_migration_trials --days 7

User source: explicit --user-ids, else the Clerk users list (needs
CLERK_SECRET_KEY). Admins in BILLING_ADMIN_USER_IDS are skipped by default
(they bypass Stripe via the env allowlist; --include-admins to override).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

from app.billing import config
from app.billing.store import Store

CLERK_API_BASE = "https://api.clerk.com/v1"


def _admin_ids() -> set[str]:
    raw = os.getenv("BILLING_ADMIN_USER_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def fetch_clerk_user_ids() -> list[str]:
    """Page through the Clerk users list and return all user_ids."""
    secret = os.getenv("CLERK_SECRET_KEY", "").strip()
    if not secret:
        sys.exit("CLERK_SECRET_KEY not set (needed to list users; or pass --user-ids)")
    ids: list[str] = []
    offset, limit = 0, 100
    with httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {secret}"}) as client:
        while True:
            resp = client.get(f"{CLERK_API_BASE}/users", params={"limit": limit, "offset": offset})
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            ids.extend(u["id"] for u in batch if u.get("id"))
            if len(batch) < limit:
                break
            offset += limit
    return ids


def main() -> None:
    p = argparse.ArgumentParser(description="Seed migration trial grants.")
    p.add_argument("--days", type=int, default=config.BILLING_MIGRATION_TRIAL_DAYS,
                   help="trial length in days (default from BILLING_MIGRATION_TRIAL_DAYS)")
    p.add_argument("--user-ids", type=str, default="",
                   help="comma-separated Clerk user_ids (skips the Clerk API)")
    p.add_argument("--include-admins", action="store_true",
                   help="also grant to BILLING_ADMIN_USER_IDS (default: skip them)")
    p.add_argument("--dry-run", action="store_true", help="preview, write nothing")
    args = p.parse_args()

    if args.user_ids.strip():
        user_ids = [x.strip() for x in args.user_ids.split(",") if x.strip()]
    else:
        user_ids = fetch_clerk_user_ids()

    admins = set() if args.include_admins else _admin_ids()
    expires_at = time.time() + args.days * 86_400

    store = Store()  # BILLING_DB_PATH
    seeded = skipped_existing = skipped_admin = 0
    for uid in user_ids:
        if uid in admins:
            skipped_admin += 1
            continue
        if store.get_grant(uid) is not None:
            skipped_existing += 1
            continue
        if args.dry_run:
            print(f"[dry-run] would grant Pro migration-trial -> {uid} (expires in {args.days}d)")
        else:
            store.upsert_grant(uid, "Pro", reason="migration-trial",
                               granted_by="seed_migration_trials", expires_at=expires_at)
        seeded += 1

    verb = "would seed" if args.dry_run else "seeded"
    print(f"\n{verb} {seeded} trial grant(s); skipped {skipped_existing} with an existing "
          f"grant, {skipped_admin} admin(s). Store: {store.path}")
    store.close()


if __name__ == "__main__":
    main()
