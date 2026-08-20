"""Grant per-user PREFERENTIAL trial days (Path B / B1, decision Adrian #4).

Some clients/partners get more trial days than the default. This is an ADMIN
tool only — there is no public endpoint (anti-abuse: the day count can only be
set server-side, by someone with shell access to the billing store). The grant
is keyed by Clerk user_id and consumed ONE-SHOT at the user's next Checkout
(store.consume_trial_override), so it cannot be recycled across attempts.

B1 means the card is STILL always collected at Checkout; only the trial length
changes. Anti-abuse fingerprint (card) is unchanged.

Usage (from backend/):
    # preview
    python -m scripts.set_trial_override --user-ids user_abc --days 14 --dry-run
    # grant 14 days to two users
    python -m scripts.set_trial_override --user-ids user_abc,user_def --days 14 \
        --reason "socio Al" --granted-by adrian
    # list every override (pending + consumed)
    python -m scripts.set_trial_override --list
    # revoke (delete) a pending/consumed override
    python -m scripts.set_trial_override --user-ids user_abc --revoke

Notes:
  - --days must be 1..30 (MIN/MAX_TRIAL_OVERRIDE_DAYS). Re-running --days for a
    user RE-ARMS the override (consumed_at back to NULL) — a deliberate re-grant.
  - Points EDGECUTE_BILLING_DB_PATH at the same store the app uses; run it in the
    environment (container) whose store you want to change.
"""
from __future__ import annotations

import argparse
import sys
import time

from app.billing.store import (
    MAX_TRIAL_OVERRIDE_DAYS,
    MIN_TRIAL_OVERRIDE_DAYS,
    Store,
)


def _fmt_ts(ts) -> str:
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _print_list(store: Store) -> None:
    rows = store.list_trial_overrides()
    if not rows:
        print("(no trial overrides)")
        return
    print(f"{'user_id':<40} {'days':>4}  {'state':<9} {'granted_by':<16} reason")
    for o in rows:
        state = "consumed" if o.consumed_at else "pending"
        print(f"{o.user_id:<40} {o.days:>4}  {state:<9} {(o.granted_by or '-'):<16} {o.reason or '-'}")


def main() -> None:
    p = argparse.ArgumentParser(description="Set per-user preferential trial days (Path B).")
    p.add_argument("--user-ids", type=str, default="",
                   help="comma-separated Clerk user_ids")
    p.add_argument("--days", type=int, default=None,
                   help=f"trial length, {MIN_TRIAL_OVERRIDE_DAYS}..{MAX_TRIAL_OVERRIDE_DAYS}")
    p.add_argument("--reason", type=str, default=None, help="free-text note (audit)")
    p.add_argument("--granted-by", type=str, default="set_trial_override",
                   help="who granted it (audit)")
    p.add_argument("--revoke", action="store_true", help="delete the override(s) instead of setting")
    p.add_argument("--list", action="store_true", help="list all overrides and exit")
    p.add_argument("--dry-run", action="store_true", help="preview, write nothing")
    args = p.parse_args()

    store = Store()  # EDGECUTE_BILLING_DB_PATH
    try:
        if args.list:
            _print_list(store)
            return

        user_ids = [x.strip() for x in args.user_ids.split(",") if x.strip()]
        if not user_ids:
            sys.exit("--user-ids is required (or use --list)")

        if args.revoke:
            for uid in user_ids:
                if args.dry_run:
                    print(f"[dry-run] would revoke override -> {uid}")
                else:
                    store.delete_trial_override(uid)
                    print(f"revoked override -> {uid}")
            return

        if args.days is None:
            sys.exit("--days is required when granting (or use --revoke / --list)")
        if not (MIN_TRIAL_OVERRIDE_DAYS <= args.days <= MAX_TRIAL_OVERRIDE_DAYS):
            sys.exit(f"--days must be {MIN_TRIAL_OVERRIDE_DAYS}..{MAX_TRIAL_OVERRIDE_DAYS}, got {args.days}")

        for uid in user_ids:
            if args.dry_run:
                print(f"[dry-run] would grant {args.days}d preferential trial -> {uid}")
            else:
                store.set_trial_override(uid, args.days, reason=args.reason,
                                         granted_by=args.granted_by)
                print(f"granted {args.days}d preferential trial -> {uid}")

        print(f"\nStore: {store.path}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
