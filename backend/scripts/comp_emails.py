"""Manage the COURTESY (comped) email list (Fase 3).

Colleagues on this list get FULL product access for FREE — same as a paying Pro
(the 4 modules, no Market Analysis, no admin powers), no card, no charge,
indefinitely. It is managed by EMAIL (no need to look up a Clerk user_id) and
lives in the billing store (SQLite), so adding/removing needs NO Coolify redeploy.

On login the /me summary reads the user's TRUSTED email from the Clerk JWT; if it
is on this list it materializes a perpetual Pro grant (reason='comped') keyed by
user_id — so it works for the product gate too, and auto-applies the moment an
invited colleague registers. Removing an email revokes on their next /me.

REQUIREMENT: the Clerk JWT template must include an `email` claim (dashboard),
otherwise the trusted email is absent and nothing materializes.

Usage (from backend/):
    python -m scripts.comp_emails --list
    python -m scripts.comp_emails --add alice@x.com,bob@y.com --granted-by adrian
    python -m scripts.comp_emails --remove alice@x.com
    python -m scripts.comp_emails --add alice@x.com --dry-run

Notes:
  - Emails are normalized (lower/trim). Run it in the environment (container)
    whose store you want to change (EDGECUTE_BILLING_DB_PATH).
"""
from __future__ import annotations

import argparse
import sys

from app.billing.store import Store


def _print_list(store: Store) -> None:
    rows = store.list_comped_emails()
    if not rows:
        print("(no comped emails)")
        return
    print(f"{len(rows)} comped email(s):")
    for e in rows:
        print(f"  {e}")


def main() -> None:
    p = argparse.ArgumentParser(description="Manage the courtesy (comped) email list.")
    p.add_argument("--add", type=str, default="", help="comma-separated emails to add")
    p.add_argument("--remove", type=str, default="", help="comma-separated emails to remove")
    p.add_argument("--granted-by", type=str, default="comp_emails", help="who granted it (audit)")
    p.add_argument("--list", action="store_true", help="list all comped emails and exit")
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

        for email in adds:
            if args.dry_run:
                print(f"[dry-run] would add comped -> {email}")
            else:
                store.add_comped_email(email, granted_by=args.granted_by)
                print(f"added comped -> {email}")
        for email in removes:
            if args.dry_run:
                print(f"[dry-run] would remove comped -> {email}")
            else:
                store.remove_comped_email(email)
                print(f"removed comped -> {email}  (revokes on their next /me)")

        print(f"\nStore: {store.path}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
