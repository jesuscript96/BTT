"""Minimal admin CLI for the public API store.

Usage (from backend/):
    python -m app.api_public.admin create-key --owner user_123 [--test] [--plan default]
    python -m app.api_public.admin revoke-key --id key_abc123
    python -m app.api_public.admin usage --id key_abc123

The store path follows EDGECUTE_STORE_PATH (default ./edgecute_api.sqlite).
The plaintext key is printed ONCE on creation — store it safely.
"""
from __future__ import annotations

import argparse
import sys

from app.api_public.core.store import Store


def _store() -> Store:
    return Store()


def cmd_create_key(args: argparse.Namespace) -> int:
    s = _store()
    token, row = s.create_api_key(owner_id=args.owner, plan=args.plan, test=args.test)
    s.close()
    print("API key created. Store the token now — it is shown only once:\n")
    print(f"  key_id : {row.id}")
    print(f"  prefix : {row.prefix}")
    print(f"  owner  : {row.owner_id}")
    print(f"  plan   : {row.plan}")
    print(f"  token  : {token}")
    return 0


def cmd_revoke_key(args: argparse.Namespace) -> int:
    s = _store()
    s.revoke_key(args.id)
    s.close()
    print(f"Revoked {args.id}")
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    s = _store()
    usage = s.usage_since(args.id, 0.0)
    s.close()
    print(f"Usage for {args.id}: {usage}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="edgecute-admin", description="Edgecute API key admin")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create-key", help="Create an API key")
    p_create.add_argument("--owner", default=None, help="Owner id (e.g. Clerk user_id)")
    p_create.add_argument("--plan", default="default")
    p_create.add_argument("--test", action="store_true", help="Mint an ek_test_ sandbox key")
    p_create.set_defaults(func=cmd_create_key)

    p_revoke = sub.add_parser("revoke-key", help="Revoke an API key")
    p_revoke.add_argument("--id", required=True)
    p_revoke.set_defaults(func=cmd_revoke_key)

    p_usage = sub.add_parser("usage", help="Show usage for a key")
    p_usage.add_argument("--id", required=True)
    p_usage.set_defaults(func=cmd_usage)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
