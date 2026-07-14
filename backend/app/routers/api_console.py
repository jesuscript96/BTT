"""Developer console (control plane) for the Edgecute Backtest API.

Human-facing, **Clerk-authenticated** (NOT API-key — that's the data plane). Lets a
logged-in user manage their API keys, see usage, and view billing/plan. Operates on
the SAME api_public store, scoped by owner_id = Clerk user_id.

Mounted in the MAIN app (which already has Clerk + web CORS). The public API
(app.api_public.app) stays purely machine-facing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.auth.clerk import get_current_user_id
from app.api_public import config
from app.api_public.core.auth import PLANS
from app.api_public.core.store import ApiKeyRow, get_store
from app.entitlements.middleware import require

# Guarda a nivel de router: los 9 endpoints son del portal, ninguno se comparte con
# otra sección. Sin esto la consola (claves, uso, facturación) quedaba abierta a
# cualquier usuario con sesión: el sidebar escondía el enlace, pero /developers se
# alcanzaba tecleando la URL.
router = APIRouter(
    prefix="/api/console",
    tags=["API Console"],
    dependencies=[Depends(require("api.portal.access"))],
)

# When Clerk auth is disabled (dev), all console calls resolve to this owner so
# the dashboard is usable locally without logging in.
DEV_OWNER = "dev_user"


def _owner(authorization: Optional[str]) -> str:
    uid = get_current_user_id(authorization)  # raises 401 if auth enabled & no token
    return uid or DEV_OWNER


def _start_of_month_ts() -> float:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def _plan_info(plan_name: str) -> dict:
    plan = PLANS.get(plan_name, config.DEFAULT_PLAN)
    return {
        "name": plan.get("name", plan_name),
        "limits": {
            "max_ticker_days_per_run": plan.get("max_ticker_days_per_run", config.MAX_TICKER_DAYS_PER_RUN),
            "rate_limit_rpm": plan.get("rate_limit_rpm", config.RATE_LIMIT_RPM),
        },
        # Price intentionally absent: pricing is a deferred product decision.
        "price": None,
    }


def _key_public(k: ApiKeyRow) -> dict:
    """Never expose the hash or the plaintext token."""
    return {
        "id": k.id,
        "prefix": k.prefix,
        "label": k.label,
        "status": k.status,
        "is_test": k.is_test,
        "plan": k.plan,
        "created_at": k.created_at,
        "last_used_at": k.last_used_at,
    }


def _onboarding(keys: list[ApiKeyRow], usage: dict) -> list[dict]:
    has_key = len(keys) > 0
    has_used = any(k.last_used_at for k in keys)
    has_run = usage.get("runs", 0) > 0
    return [
        {"id": "create_key", "label": "Crea tu primera API key", "done": has_key},
        {"id": "install_mcp", "label": "Instala el MCP (npx @edgecute/mcp) o el cliente", "done": has_used},
        {"id": "first_backtest", "label": "Lanza tu primer backtest", "done": has_run},
    ]


# ── Overview ─────────────────────────────────────────────────────────────────
@router.get("/overview")
def overview(authorization: Optional[str] = Header(default=None)):
    owner = _owner(authorization)
    store = get_store()
    keys = store.list_keys_by_owner(owner)
    plan_name = next((k.plan for k in keys if k.status == "active"), "default")
    since = _start_of_month_ts()
    usage = store.usage_for_owner(owner, since)
    return {
        "owner_id": owner,
        "plan": _plan_info(plan_name),
        "usage_period": {"label": "Este mes", "since": since, **usage},
        "keys": {
            "total": len(keys),
            "active": sum(1 for k in keys if k.status == "active"),
        },
        "activity": store.recent_activity_for_owner(owner, 10),
        "onboarding": _onboarding(keys, usage),
        "docs_url": config.DOCS_URL,
    }


# ── API keys ─────────────────────────────────────────────────────────────────
class CreateKeyRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=80)
    test: bool = False


@router.get("/keys")
def list_keys(authorization: Optional[str] = Header(default=None)):
    owner = _owner(authorization)
    keys = get_store().list_keys_by_owner(owner)
    return {"keys": [_key_public(k) for k in keys]}


@router.post("/keys")
def create_key(req: CreateKeyRequest, authorization: Optional[str] = Header(default=None)):
    owner = _owner(authorization)
    store = get_store()
    active = [k for k in store.list_keys_by_owner(owner) if k.status == "active"]
    if len(active) >= config.MAX_KEYS_PER_OWNER:
        raise HTTPException(
            status_code=409,
            detail=f"Has alcanzado el máximo de API keys activas ({config.MAX_KEYS_PER_OWNER}). Revoca alguna.",
        )
    token, row = store.create_api_key(owner_id=owner, test=req.test, label=req.label)
    # Plaintext returned ONCE — the frontend must tell the user to copy it now.
    return {"key": _key_public(row), "token": token, "token_shown_once": True}


@router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: str, authorization: Optional[str] = Header(default=None)):
    owner = _owner(authorization)
    store = get_store()
    row = store.get_key_by_id(key_id)
    # 404 (not 403) when it isn't theirs — don't reveal existence of others' keys.
    if row is None or row.owner_id != owner:
        raise HTTPException(status_code=404, detail="API key no encontrada.")
    store.revoke_key(key_id)
    return {"ok": True, "id": key_id, "status": "revoked"}


# ── Usage & billing ──────────────────────────────────────────────────────────
@router.get("/usage")
def usage(authorization: Optional[str] = Header(default=None)):
    owner = _owner(authorization)
    store = get_store()
    return {
        "this_month": {"label": "Este mes", **store.usage_for_owner(owner, _start_of_month_ts())},
        "all_time": {"label": "Histórico", **store.usage_for_owner(owner, 0.0)},
        "activity": store.recent_activity_for_owner(owner, 50),
    }


@router.get("/billing")
def billing(authorization: Optional[str] = Header(default=None)):
    owner = _owner(authorization)
    store = get_store()
    keys = store.list_keys_by_owner(owner)
    plan_name = next((k.plan for k in keys if k.status == "active"), "default")
    plan = _plan_info(plan_name)
    usage = store.usage_for_owner(owner, _start_of_month_ts())
    return {
        "plan": plan,
        "usage_this_month": usage,
        # Stripe is wired later (docs/b2d-gateway/07): structure ready, no data yet.
        "invoices": [],
        "stripe": {"connected": False, "note": "Facturación con Stripe próximamente."},
        "upgrade_url": config.UPGRADE_URL or None,
    }


@router.get("/plans")
def plans(authorization: Optional[str] = Header(default=None)):
    _owner(authorization)  # require auth
    return {
        "plans": [_plan_info(name) for name in PLANS.keys()],
        "upgrade_url": config.UPGRADE_URL or None,
        "note": "Los planes de pago y precios se anunciarán pronto.",
    }


# ── Playground (try the API from the dashboard) ──────────────────────────────
# Clerk-authed, server-side, cheap (no engine, no API key needed). Lets the user
# discover indicators and validate strategies before writing code.
@router.get("/playground/indicators")
def playground_indicators(
    category: Optional[str] = None, authorization: Optional[str] = Header(default=None)
):
    _owner(authorization)
    from app.api_public.modules.backtest.catalog import build_catalog

    entries = build_catalog()
    if category:
        entries = [e for e in entries if e["category"].lower() == category.lower()]
    return {"indicators": entries}


class PlaygroundValidate(BaseModel):
    strategy: dict


@router.post("/playground/validate")
def playground_validate(
    body: PlaygroundValidate, authorization: Optional[str] = Header(default=None)
):
    _owner(authorization)
    from pydantic import ValidationError
    from app.schemas.strategy import StrategyCreate

    try:
        StrategyCreate(**body.strategy)
        return {"valid": True, "errors": []}
    except ValidationError as exc:
        errors = [
            {"path": ".".join(str(p) for p in e.get("loc", [])), "message": e.get("msg", "invalid")}
            for e in exc.errors()
        ]
        return {"valid": False, "errors": errors}
