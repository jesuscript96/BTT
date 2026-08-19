"""Billing HTTP surface (Fase 2C). Clerk-authed.

Mounted under /api/billing ONLY when BILLING_ENABLED (main.py) → dormant in prod
until cutover. Two outbound actions for now: start Checkout, open Billing Portal.
The webhook and the billing summary endpoint (GET /me) arrive in 2D/2F.

The service is provided via get_billing_service so tests can override it with a
fake gateway + temp store (pattern: api_public get_facade).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth.clerk import get_current_user_id
from app.billing import config
from app.billing import store as store_mod
from app.billing import webhook as webhook_mod
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


class SyncRequest(BaseModel):
    session_id: str


@router.get("/me")
def billing_me(
    user_id: Optional[str] = Depends(get_current_user_id),
    svc: BillingService = Depends(get_billing_service),
):
    """Read-only billing summary for the current user (no Stripe call)."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return svc.get_billing_summary(user_id)


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


@router.post("/checkout/sync")
def checkout_sync(
    body: SyncRequest,
    user_id: Optional[str] = Depends(get_current_user_id),
    svc: BillingService = Depends(get_billing_service),
):
    """Synchronous confirmation on the success_url (§4 step 5a): materializes the
    subscription immediately so access does not wait on the webhook."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        sub = svc.sync_checkout_return(body.session_id)
    except BillingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except StripeError as exc:
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")
    return {"synced": sub is not None, "status": sub.status if sub else None}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Stripe -> us. NO Clerk auth: authenticity is the signature. Idempotent:
    duplicates (Stripe retries) are skipped. On handler failure we return 5xx so
    Stripe retries (the event is not marked processed)."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = webhook_mod.verify_and_construct_event(
            payload, sig, config.STRIPE_WEBHOOK_SECRET
        )
    except webhook_mod.WebhookError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    event_id = event.get("id")
    etype = event.get("type", "")
    store = store_mod.get_store()
    if event_id and store.is_event_processed(event_id):
        return {"status": "duplicate"}
    webhook_mod.process_event(event, store)   # raises -> 500 -> Stripe retries
    if event_id:
        store.mark_event_processed(event_id, etype)
    return {"status": "ok"}
