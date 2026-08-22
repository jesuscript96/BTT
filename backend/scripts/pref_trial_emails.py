"""Manage the PREFERENTIAL trial email list (Fase 3, Path B by email).

People on this list get a preferential trial length (e.g. 14 days) instead of the
default window, the first time they subscribe. Managed by EMAIL (no Clerk user_id
lookup) and lives in the billing store (SQLite), so adding/removing needs NO
Coolify redeploy.

On login the /me summary reads the user's TRUSTED email from the Clerk JWT; if it
carries a preferential trial and the user has NO override yet, it seeds a ONE-SHOT
trial_override keyed by user_id. It seeds ONCE only (never re-arms), so a consumed
preferential trial cannot recycle on every login; the one-shot is consumed at the
next Checkout. Card is ALWAYS collected (B1) — only the day count changes.

Migration-proof: after migrating Clerk to prod the same email re-seeds under the
new user_id automatically, so there is no manual re-seed to run.

REQUIREMENT: the Clerk JWT template must include an `email` claim (and
`email_verified`), otherwise the trusted email is absent and nothing seeds.

Usage (from backend/):
    python -m scripts.pref_trial_emails --list
    python -m scripts.pref_trial_emails --add alice@x.com,bob@y.com --days 14 --granted-by adrian
    python -m scripts.pref_trial_emails --remove alice@x.com
    python -m scripts.pref_trial_emails --add alice@x.com --days 14 --dry-run

Notes:
  - days must be 1..30 (validated). Emails are normalized (lower/trim). Run it in
    the environment (container) whose store you want to change
    (EDGECUTE_BILLING_DB_PATH).
  - Removing an email stops FUTURE seeding; it does NOT revoke an override already
    seeded on a user_id (use scripts against trial_overrides for that).
"""
from __future__ import annotations

import argparse
import sys

from app.billing.store import Store


def _print_list(store: Store) -> None:
    rows = store.list_trial_override_emails()
    if not rows:
        print("(no preferential-trial emails)")
        return
    print(f"{len(rows)} preferential-trial email(s):")
    for email, days in rows:
        print(f"  {email}  ->  {days}d")


def main() -> None:
    p = argparse.ArgumentParser(description="Manage the preferential-trial email list.")
    p.add_argument("--add", type=str, default="", help="comma-separated emails to add")
    p.add_argument("--remove", type=str, default="", help="comma-separated emails to remove")
    p.add_argument("--days", type=int, default=0, help="preferential trial length (1..30), required with --add")
    p.add_argument("--granted-by", type=str, default="pref_trial_emails", help="who granted it (audit)")
    p.add_argument("--list", action="store_true", help="list all preferential-trial emails and exit")
    p.add_argument("--dry-run", action="store_true", help="preview, write nothing")
    args = p.parse_args()

    store = Store()  # EDGECUTE_BILLING_DB_PATH
    try:
        if args.list:
            _print_list(store)
            return

        adds = [x.strip() for x in args.add.split(",") if x.strip()]
        removes = [x.strip() for x in args.remove.split(",") if x.strip()]
        if not adds and not removes:
            sys.exit("nothing to do: use --add, --remove or --list")
        if adds and not (1 <= args.days <= 30):
            sys.exit("--add requires --days between 1 and 30")

        for email in adds:
            if args.dry_run:
                print(f"[dry-run] would add preferential {args.days}d -> {email}")
            else:
                store.add_trial_override_email(email, args.days, granted_by=args.granted_by)
                print(f"added preferential {args.days}d -> {email}")
        for email in removes:
            if args.dry_run:
                print(f"[dry-run] would remove preferential -> {email}")
            else:
                store.remove_trial_override_email(email)
                print(f"removed preferential -> {email}  (stops future seeding)")

        print(f"\nStore: {store.path}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
