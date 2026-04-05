"""Webhook routes — register, list, delete webhook subscriptions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.auth_service import verify_access_token
from app.services.database import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _get_user_id(authorization: str) -> int:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    payload = verify_access_token(authorization[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return int(payload["sub"])


class CreateWebhookRequest(BaseModel):
    url: str = Field(..., min_length=10, max_length=500, pattern=r"^https://")
    events: list[str] = Field(default=["scan.complete"])


@router.post("")
async def route_create_webhook(body: CreateWebhookRequest, authorization: str = Header(default="")):
    """Register a webhook endpoint. URL must be HTTPS."""
    user_id = _get_user_id(authorization)
    db = get_db()

    # Limit webhooks per user
    existing = db.fetch_all("SELECT id FROM webhook_subscriptions WHERE user_id = ? AND is_active = 1", (user_id,))
    if len(existing) >= 5:
        raise HTTPException(status_code=400, detail="Maximum 5 active webhooks allowed.")

    secret = secrets.token_hex(32)
    events_str = ",".join(body.events)
    wh_id = db.execute(
        "INSERT INTO webhook_subscriptions (user_id, url, events, secret) VALUES (?, ?, ?, ?)",
        (user_id, body.url, events_str, secret),
    )
    logger.info("webhook_created", user_id=user_id, url=body.url)
    return {"id": wh_id, "url": body.url, "events": body.events, "secret": secret}


@router.get("")
async def route_list_webhooks(authorization: str = Header(default="")):
    """List all active webhooks for the user."""
    user_id = _get_user_id(authorization)
    db = get_db()
    rows = db.fetch_all(
        "SELECT id, url, events, is_active, created_at FROM webhook_subscriptions WHERE user_id = ?",
        (user_id,),
    )
    return {"webhooks": [
        {**dict(r), "events": r["events"].split(",") if r.get("events") else []}
        for r in rows
    ]}


@router.delete("/{webhook_id}")
async def route_delete_webhook(webhook_id: int, authorization: str = Header(default="")):
    """Deactivate a webhook."""
    user_id = _get_user_id(authorization)
    db = get_db()
    wh = db.fetch_one("SELECT user_id FROM webhook_subscriptions WHERE id = ?", (webhook_id,))
    if not wh or wh["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    db.execute("UPDATE webhook_subscriptions SET is_active = 0 WHERE id = ?", (webhook_id,))
    return {"status": "deleted"}


async def fire_webhooks(user_id: int, event: str, payload: dict[str, Any]) -> None:
    """Send webhook notifications for a user's active subscriptions.

    Called after scan completion. Best-effort — failures are logged but not raised.
    """
    db = get_db()
    subs = db.fetch_all(
        "SELECT url, secret, events FROM webhook_subscriptions "
        "WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )
    if not subs:
        return

    for sub in subs:
        events = sub["events"].split(",") if sub.get("events") else []
        if event not in events and "*" not in events:
            continue

        body_bytes = __import__("json").dumps(payload).encode()
        signature = hmac.new(sub["secret"].encode(), body_bytes, hashlib.sha256).hexdigest()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    sub["url"],
                    content=body_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-PlagiarismGuard-Signature": f"sha256={signature}",
                        "X-PlagiarismGuard-Event": event,
                    },
                )
                logger.info("webhook_delivered", url=sub["url"], status=resp.status_code)
        except Exception as exc:
            logger.warning("webhook_delivery_failed", url=sub["url"], error=str(exc)[:100])
