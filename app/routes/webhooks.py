"""Webhook routes — register, list, delete webhook subscriptions."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any
import asyncio

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.auth_service import verify_access_token
from app.services.database import get_db
from app.utils.logger import get_logger
from app.utils.ssrf import is_private_url

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _is_private_url(url: str) -> bool:
    """Backwards-compat shim — delegates to the shared SSRF guard."""
    return is_private_url(url)


def _get_user_id(authorization: str) -> int:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    payload = verify_access_token(authorization[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    try:
        return int(payload["sub"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token payload.")


class CreateWebhookRequest(BaseModel):
    url: str = Field(..., min_length=10, max_length=500, pattern=r"^https://")
    events: list[str] = Field(default=["scan.complete"])


@router.post("")
async def route_create_webhook(body: CreateWebhookRequest, authorization: str = Header(default="")):
    """Register a webhook endpoint. URL must be HTTPS."""
    user_id = _get_user_id(authorization)

    # Block SSRF: reject URLs that resolve to private/internal IPs
    if _is_private_url(body.url):
        raise HTTPException(status_code=400, detail="Webhook URL must not resolve to a private or internal address.")

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


@router.get("/deliveries")
async def route_list_webhook_deliveries(authorization: str = Header(default=""), limit: int = 25):
    """List recent webhook delivery attempts for the authenticated user."""
    user_id = _get_user_id(authorization)
    limit = max(1, min(int(limit or 25), 100))
    db = get_db()
    rows = db.fetch_all(
        "SELECT d.id, d.webhook_id, w.url, d.event, d.status, d.attempts, "
        "d.response_code, d.last_error, d.created_at, d.delivered_at "
        "FROM webhook_deliveries d JOIN webhook_subscriptions w ON d.webhook_id = w.id "
        "WHERE d.user_id = ? ORDER BY d.created_at DESC",
        (user_id,),
    )
    return {"deliveries": [dict(r) for r in rows[:limit]]}


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


@router.post("/deliveries/{delivery_id}/replay")
async def route_replay_webhook_delivery(delivery_id: int, authorization: str = Header(default="")):
    """Replay a previously recorded webhook delivery."""
    user_id = _get_user_id(authorization)
    db = get_db()
    row = db.fetch_one(
        "SELECT d.id, d.webhook_id, d.user_id, d.event, d.payload_json, "
        "w.url, w.secret, w.is_active "
        "FROM webhook_deliveries d JOIN webhook_subscriptions w ON d.webhook_id = w.id "
        "WHERE d.id = ?",
        (delivery_id,),
    )
    if not row or int(row["user_id"]) != user_id:
        raise HTTPException(status_code=404, detail="Webhook delivery not found.")
    if not row.get("is_active"):
        raise HTTPException(status_code=400, detail="Webhook is inactive.")

    payload = json.loads(row["payload_json"])
    status = await _deliver_webhook(
        delivery_id=int(row["id"]),
        url=row["url"],
        secret=row["secret"],
        event=row["event"],
        payload=payload,
        max_attempts=1,
    )
    return {"status": status}


def _create_delivery(user_id: int, webhook_id: int, event: str, payload: dict[str, Any]) -> int:
    db = get_db()
    return db.execute(
        "INSERT INTO webhook_deliveries (webhook_id, user_id, event, payload_json, status) "
        "VALUES (?, ?, ?, ?, 'pending')",
        (webhook_id, user_id, event, json.dumps(payload, separators=(",", ":"))),
    )


def _record_delivery_attempt(
    delivery_id: int,
    *,
    status: str,
    attempts: int,
    response_code: int | None = None,
    response_body: str | None = None,
    last_error: str | None = None,
) -> None:
    db = get_db()
    delivered_clause = ", delivered_at = CURRENT_TIMESTAMP" if status == "delivered" else ""
    db.execute(
        "UPDATE webhook_deliveries SET status = ?, attempts = ?, response_code = ?, "
        f"response_body = ?, last_error = ?{delivered_clause} WHERE id = ?",
        (status, attempts, response_code, (response_body or "")[:1000], (last_error or "")[:1000], delivery_id),
    )


async def _deliver_webhook(
    *,
    delivery_id: int,
    url: str,
    secret: str,
    event: str,
    payload: dict[str, Any],
    max_attempts: int = 3,
) -> str:
    body_bytes = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    last_status = "failed"

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            await asyncio.sleep(min(2 ** (attempt - 2), 4))

        try:
            # Re-check at fire time to defend against DNS rebinding
            if _is_private_url(url):
                _record_delivery_attempt(
                    delivery_id,
                    status="blocked",
                    attempts=attempt,
                    last_error="Webhook URL resolved to a private/internal address.",
                )
                logger.warning("webhook_blocked_private_ip", url=url)
                return "blocked"

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    content=body_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-PlagiarismGuard-Signature": f"sha256={signature}",
                        "X-PlagiarismGuard-Event": event,
                    },
                )
                ok = 200 <= resp.status_code < 300
                last_status = "delivered" if ok else "failed"
                _record_delivery_attempt(
                    delivery_id,
                    status=last_status,
                    attempts=attempt,
                    response_code=resp.status_code,
                    response_body=resp.text,
                    last_error=None if ok else f"HTTP {resp.status_code}",
                )
                logger.info("webhook_delivered", url=url, status=resp.status_code, attempt=attempt)
                if ok:
                    return "delivered"
        except Exception as exc:
            last_status = "failed"
            _record_delivery_attempt(
                delivery_id,
                status="failed",
                attempts=attempt,
                last_error=str(exc)[:1000],
            )
            logger.warning("webhook_delivery_failed", url=url, error=str(exc)[:100], attempt=attempt)

    return last_status


async def fire_webhooks(user_id: int, event: str, payload: dict[str, Any]) -> None:
    """Send webhook notifications for a user's active subscriptions.

    Called after scan completion. Best-effort — failures are logged but not raised.
    """
    db = get_db()
    subs = db.fetch_all(
        "SELECT id, url, secret, events FROM webhook_subscriptions "
        "WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )
    if not subs:
        return

    for sub in subs:
        events = sub["events"].split(",") if sub.get("events") else []
        if event not in events and "*" not in events:
            continue
        delivery_id = _create_delivery(user_id, int(sub["id"]), event, payload)
        await _deliver_webhook(
            delivery_id=delivery_id,
            url=sub["url"],
            secret=sub["secret"],
            event=event,
            payload=payload,
        )
