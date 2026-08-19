"""Billing HTTP surface (Fase 2C). Clerk-authed.

Mounted under /api/billing ONLY when BILLING_ENABLED (main.py) → dormant in prod
until cutover. Two outbound actions for now: start Checkout, open Billing Portal.
The webhook and the billing summary endpoint (GET /me) arrive in 2D/2F.

The service is provided via get_billing_service so tests can override it with a
fake gateway + temp store (pattern: api_public get_facade).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.clerk import get_current_user_id
from app.billing.service import BillingError, BillingService
from app.billing.stripe_client import StripeError

router = APIRouter()


def get_billing_service() -> BillingService:
    """Default provider — builds the real service (and Stripe gateway). Overridden
    in tests. Constructed per-request; cheap (SDK config only)."""
    return BillingService()


class CheckoutRequest(BaseModel):
    # email comes from the frontend's Clerk session for now (MVP); 2F can source
    # it from the verified server-side claim instead of trusting the client.
    email: Optional[str] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class PortalRequest(BaseModel):
    return_url: Optional[str] = None


@router.post("/checkout")
def create_checkout(
    body: CheckoutRequest,
    user_id: Optional[str] = Depends(get_current_user_id),
    svc: BillingService = Depends(get_billing_service),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        session = svc.start_subscription_checkout(
            user_id, body.email, body.success_url, body.cancel_url
        )
    except BillingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except StripeError as exc:
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")
    return {"checkout_url": session["url"], "session_id": session["id"]}


@router.post("/portal")
def create_portal(
    body: PortalRequest,
    user_id: Optional[str] = Depends(get_current_user_id),
    svc: BillingService = Depends(get_billing_service),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        url = svc.open_billing_portal(user_id, body.return_url)
    except BillingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except StripeError as exc:
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")
    return {"portal_url": url}
