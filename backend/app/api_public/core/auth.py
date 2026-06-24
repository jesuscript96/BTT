"""API-key authentication.

Developer API keys (NOT Clerk session JWTs — Clerk is for the human web session;
docs/b2d-gateway/05 §3). `Authorization: Bearer ek_(live|test)_…`. The key's owner
can be a Clerk user_id, which is the bridge to whatever entitlement policy the app
defines later (that policy is NOT decided here).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from fastapi import Request

from app.api_public import config
from app.api_public.core.errors import ApiError
from app.api_public.core.store import get_store


PLANS = {"default": config.DEFAULT_PLAN}


@dataclass
class Principal:
    api_key_id: str
    owner_id: Optional[str]
    key_prefix: str
    plan_name: str
    is_test: bool
    plan: dict = field(default_factory=dict)

    @property
    def max_ticker_days(self) -> int:
        return int(self.plan.get("max_ticker_days_per_run", config.MAX_TICKER_DAYS_PER_RUN))

    @property
    def rate_limit_rpm(self) -> int:
        return int(self.plan.get("rate_limit_rpm", config.RATE_LIMIT_RPM))


def _resolve_plan(name: str) -> dict:
    return PLANS.get(name, config.DEFAULT_PLAN)


def _extract_bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def authenticate(request: Request) -> Principal:
    """FastAPI dependency. Resolves the API key to a Principal or raises ApiError."""
    if not config.AUTH_REQUIRED:
        # Dev-only synthetic principal.
        return Principal(
            api_key_id="dev", owner_id=None, key_prefix="ek_test_dev",
            plan_name="default", is_test=True, plan=config.DEFAULT_PLAN,
        )

    token = _extract_bearer(request)
    if not token:
        raise ApiError("unauthorized", "Falta la API key. Usa 'Authorization: Bearer ek_…'.")
    if not token.startswith(("ek_live_", "ek_test_")):
        raise ApiError("invalid_api_key", "Formato de API key inválido.")

    row = get_store().get_key_by_token(token)
    if row is None:
        raise ApiError("invalid_api_key", "API key no válida.")
    if row.status != "active":
        raise ApiError("forbidden", "API key revocada.")

    get_store().touch_key(row.id)
    return Principal(
        api_key_id=row.id,
        owner_id=row.owner_id,
        key_prefix=row.prefix,
        plan_name=row.plan,
        is_test=token.startswith("ek_test_"),
        plan=_resolve_plan(row.plan),
    )
