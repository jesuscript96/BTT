"""Manage the ADMIN email list (Fase 3, decision #1).

People on this list get tier "Admin" — full internal access, no card, no charge,
above every subscription/comped state. It is managed by EMAIL (no need to look up
a Clerk user_id) and lives in the billing store (SQLite), so adding/removing needs
NO Coolify redeploy.

On login the /me summary reads the user's TRUSTED email from the Clerk JWT; if it
is on this list it materializes an Admin grant (reason='admin') keyed by user_id —
so it works for the product gate too, and auto-applies the moment an admin
registers. Removing an email revokes on their next /me. Admin WINS over comped:
an email on both lists resolves to Admin.

Migration-proof: the email survives a Clerk-instance change; the user_id doesn't.
After migrating Clerk to prod, admins keep their access with no re-seed.

REQUIREMENT: the Clerk JWT template must include an `email` claim (and
`email_verified`), otherwise the trusted email is absent and nothing materializes.

Usage (from backend/):
    python -m scripts.admin_emails --list
    python -m scripts.admin_emails --add alice@x.com,bob@y.com --granted-by adrian
    python -m scripts.admin_emails --remove alice@x.com
    python -m scripts.admin_emails --add alice@x.com --dry-run

Notes:
  - Emails are normalized (lower/trim). Run it in the environment (container)
    whose store you want to change (EDGECUTE_BILLING_DB_PATH).
"""
from __future__ import annotations

import argparse
import sys

from app.billing.store import Store


def _print_list(store: Store) -> None:
    rows = store.list_admin_emails()
    if not rows:
        print("(no admin emails)")
        return
    print(f"{len(rows)} admin email(s):")
    for e in rows:
        print(f"  {e}")


def main() -> None:
    p = argparse.ArgumentParser(description="Manage the admin email list.")
    p.add_argument("--add", type=str, default="", help="comma-separated emails to add")
    p.add_argument("--remove", type=str, default="", help="comma-separated emails to remove")
    p.add_argument("--granted-by", type=str, default="admin_emails", help="who granted it (audit)")
    p.add_argument("--list", action="store_true", help="list all admin emails and exit")
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
                print(f"[dry-run] would add admin -> {email}")
            else:
                store.add_admin_email(email, granted_by=args.granted_by)
                print(f"added admin -> {email}")
        for email in removes:
            if args.dry_run:
                print(f"[dry-run] would remove admin -> {email}")
            else:
                store.remove_admin_email(email)
                print(f"removed admin -> {email}  (revokes on their next /me)")

        print(f"\nStore: {store.path}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
