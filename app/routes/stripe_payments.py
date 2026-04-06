"""Stripe payment routes — international billing with multi-currency support.

Endpoints:
  POST /api/v1/stripe/create-checkout   — create a Stripe Checkout Session
  POST /api/v1/stripe/webhook           — handle Stripe webhook events
  POST /api/v1/stripe/portal            — create a Customer Portal session
  GET  /api/v1/stripe/plans             — list available plans with prices
"""

from __future__ import annotations

import hmac
import hashlib
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.database import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/stripe", tags=["payments"])

# ---------------------------------------------------------------------------
# Plan definitions — mirrors Razorpay tiers for international users
# ---------------------------------------------------------------------------

STRIPE_PLANS = {
    "pro_monthly": {
        "name": "Pro Monthly",
        "price_usd": 1499,  # $14.99 in cents
        "interval": "month",
        "tier": "pro",
        "features": [
            "200K words/month",
            "50 MB uploads",
            "Batch analysis (5 files)",
            "5 API keys",
            "Priority support",
        ],
    },
    "pro_yearly": {
        "name": "Pro Yearly",
        "price_usd": 14388,  # $143.88 / year ($11.99/mo)
        "interval": "year",
        "tier": "pro",
        "features": [
            "200K words/month",
            "50 MB uploads",
            "Batch analysis (5 files)",
            "5 API keys",
            "Priority support",
            "2 months free",
        ],
    },
    "premium_monthly": {
        "name": "Premium Monthly",
        "price_usd": 2999,  # $29.99
        "interval": "month",
        "tier": "premium",
        "features": [
            "500K words/month",
            "100 MB uploads",
            "Batch analysis (10 files)",
            "20 API keys",
            "Team features",
            "Webhook notifications",
            "Priority support",
        ],
    },
    "premium_yearly": {
        "name": "Premium Yearly",
        "price_usd": 28788,  # $287.88 / year ($23.99/mo)
        "interval": "year",
        "tier": "premium",
        "features": [
            "500K words/month",
            "100 MB uploads",
            "Batch analysis (10 files)",
            "20 API keys",
            "Team features",
            "Webhook notifications",
            "Priority support",
            "2 months free",
        ],
    },
}


def _get_stripe():
    """Lazy-import Stripe and configure it."""
    import stripe

    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    stripe.api_key = settings.stripe_secret_key
    return stripe


# ---------------------------------------------------------------------------
# List plans
# ---------------------------------------------------------------------------

@router.get("/plans")
async def list_plans():
    """Return available Stripe plans with pricing."""
    return {
        "plans": [
            {
                "id": plan_id,
                "name": plan["name"],
                "price_usd": plan["price_usd"],
                "price_display": f"${plan['price_usd'] / 100:.2f}",
                "interval": plan["interval"],
                "tier": plan["tier"],
                "features": plan["features"],
            }
            for plan_id, plan in STRIPE_PLANS.items()
        ],
        "publishable_key": settings.stripe_publishable_key,
    }


# ---------------------------------------------------------------------------
# Create Checkout Session
# ---------------------------------------------------------------------------

@router.post("/create-checkout")
async def create_checkout(request: Request):
    """Create a Stripe Checkout Session and return the URL."""
    stripe = _get_stripe()
    body = await request.json()
    plan_id = body.get("plan_id")
    user_id = getattr(request.state, "user_id", None)

    if not user_id:
        raise HTTPException(status_code=401, detail="Login required")
    if plan_id not in STRIPE_PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    plan = STRIPE_PLANS[plan_id]
    db = get_db()
    user = db.fetch_one("SELECT email, stripe_customer_id FROM users WHERE id = ?", (user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Re-use existing Stripe customer or create one
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        customer = stripe.Customer.create(
            email=user["email"],
            metadata={"pg_user_id": str(user_id)},
        )
        customer_id = customer.id
        # Use WHERE stripe_customer_id IS NULL to prevent race conditions
        db.execute(
            "UPDATE users SET stripe_customer_id = ? WHERE id = ? AND stripe_customer_id IS NULL",
            (customer_id, user_id),
        )

    base_url = str(request.base_url).rstrip("/")

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": plan["price_usd"],
                    "recurring": {"interval": plan["interval"]},
                    "product_data": {"name": plan["name"]},
                },
                "quantity": 1,
            }
        ],
        metadata={"pg_user_id": str(user_id), "pg_plan": plan_id, "pg_tier": plan["tier"]},
        success_url=f"{base_url}/pricing?session_id={{CHECKOUT_SESSION_ID}}&status=success",
        cancel_url=f"{base_url}/pricing?status=cancelled",
        automatic_tax={"enabled": False},
        allow_promotion_codes=True,
    )

    return {"checkout_url": session.url, "session_id": session.id}


# ---------------------------------------------------------------------------
# Customer Portal (manage subscription)
# ---------------------------------------------------------------------------

@router.post("/portal")
async def customer_portal(request: Request):
    """Create a Stripe Customer Portal session for subscription management."""
    stripe = _get_stripe()
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required")

    db = get_db()
    user = db.fetch_one("SELECT stripe_customer_id FROM users WHERE id = ?", (user_id,))
    if not user or not user.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="No active subscription")

    base_url = str(request.base_url).rstrip("/")
    session = stripe.billing_portal.Session.create(
        customer=user["stripe_customer_id"],
        return_url=f"{base_url}/pricing",
    )
    return {"portal_url": session.url}


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events (checkout.session.completed, etc.)."""
    stripe = _get_stripe()
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not settings.stripe_webhook_secret:
        logger.warning("stripe_webhook_secret_not_set")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, settings.stripe_webhook_secret
        )
    except Exception as e:
        logger.error("stripe_webhook_verify_failed", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    logger.info("stripe_webhook", event_type=event_type, id=data.get("id"))

    db = get_db()

    if event_type == "checkout.session.completed":
        meta = data.get("metadata", {})
        user_id = meta.get("pg_user_id")
        tier = meta.get("pg_tier", "pro")
        customer_id = data.get("customer")

        if user_id:
            db.execute(
                "UPDATE users SET plan_type = ?, stripe_customer_id = ? WHERE id = ?",
                (tier, customer_id, int(user_id)),
            )
            # Record the payment so _check_trial_expiry won't downgrade paying users
            try:
                amount = data.get("amount_total", 0)
                currency = data.get("currency", "usd")
                stripe_session_id = data.get("id", "")
                db.execute(
                    "INSERT INTO payments (user_id, razorpay_order_id, plan_name, amount, currency, status) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (int(user_id), stripe_session_id, tier, amount, currency, "paid"),
                )
            except Exception as pay_err:
                logger.error("stripe_payment_record_failed", user_id=user_id, error=str(pay_err))
            logger.info("stripe_upgrade", user_id=user_id, tier=tier)

    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        if customer_id:
            db.execute(
                "UPDATE users SET plan_type = 'free' WHERE stripe_customer_id = ?",
                (customer_id,),
            )
            logger.info("stripe_downgrade", customer_id=customer_id)

    elif event_type == "invoice.payment_failed":
        customer_id = data.get("customer")
        logger.warning("stripe_payment_failed", customer_id=customer_id)

    return {"status": "ok"}
