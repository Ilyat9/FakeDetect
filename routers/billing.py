"""Billing webhooks + plan management (Block F.4).

Provider-agnostic normalized contract (documented compromise F-C6 in
COMPROMISES.md): real provider payloads are mapped to this contract by thin
adapters; Stripe signatures are verified via HMAC when the webhook secret is
configured. Yookassa adapter requires its shared secret header.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.config import get_secret, settings
from database import update_tenant_plan
from services.tenancy import PLAN_LIMITS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["billing"])


async def _apply_plan(tenant_id: int, plan: str, provider: str,
                      external_sub_id: str = None) -> dict:
    limits = PLAN_LIMITS.get(plan)
    if limits is None:
        raise HTTPException(status_code=400, detail=f"Unknown plan '{plan}'")
    ok = await update_tenant_plan(
        tenant_id,
        plan=plan,
        max_checks_per_month=limits["max_checks_per_month"],
        max_watches=limits["max_watches"],
        max_users=limits["max_users"],
        is_active=True,
        payment_provider=provider,
        external_sub_id=external_sub_id,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update tenant")
    return {"status": "activated", "plan": plan, **limits}


async def _cancel(tenant_id: int) -> dict:
    # Cancelled subscription: deactivate the tenant until payment resumes.
    await update_tenant_plan(tenant_id, is_active=False)
    return {"status": "cancelled"}


def _verify_stripe(payload: bytes, sig_header: str) -> None:
    secret = get_secret(settings.billing_stripe_webhook_secret)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Stripe webhook secret is not configured "
                   "(BILLING_STRIPE_WEBHOOK_SECRET)",
        )
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(","))
        timestamp, signature = parts["t"], parts["v1"]
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Malformed Stripe-Signature")

    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    age = abs(datetime.now(timezone.utc).timestamp() - int(timestamp))
    if age > 300:
        raise HTTPException(status_code=400, detail="Stripe signature timestamp too old")


@router.post("/billing/webhook/{provider}")
async def billing_webhook(request: Request, provider: str):
    """Payment-provider webhook → updates the tenant's plan and limits."""
    payload = await request.body()

    if provider == "stripe":
        _verify_stripe(payload, request.headers.get("stripe-signature", ""))
    elif provider == "yookassa":
        secret = get_secret(settings.billing_yookassa_webhook_secret)
        if not secret:
            raise HTTPException(
                status_code=503, detail="Yookassa webhook secret is not configured"
            )
        provided = request.headers.get("x-yookassa-secret", "")
        expected = hashlib.sha256(secret.encode()).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=400, detail="Invalid Yookassa secret")
    else:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    tenant_id = event.get("tenant_id")
    event_type = event.get("event", "")
    if not isinstance(tenant_id, int):
        raise HTTPException(status_code=400, detail="tenant_id (int) is required")

    if event_type == "subscription_activated":
        result = await _apply_plan(
            tenant_id, event.get("plan", "pro"), provider,
            event.get("external_sub_id"),
        )
    elif event_type == "subscription_cancelled":
        result = await _cancel(tenant_id)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported event '{event_type}'")

    logger.info(f"Billing webhook processed: {provider}/{event_type} tenant={tenant_id}")
    return JSONResponse(content=result)


class PlanChangeRequest(BaseModel):
    plan: str = Field(..., description="free | pro | business")


@router.post("/billing/plans/{tenant_id}")
async def change_plan(request: Request, tenant_id: int, body: PlanChangeRequest):
    """Manual plan change — owner of the tenant or legacy master key only."""
    from services import tenancy

    ctx = await tenancy.require_ctx(request, min_role="owner")
    if ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Owners manage only their own tenant")
    return JSONResponse(content=await _apply_plan(
        tenant_id, body.plan, "manual", external_sub_id=None
    ))