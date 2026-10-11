"""Stripe webhook: payment confirmations for website orders."""

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import payments
from ..config import settings
from ..db import get_db

log = logging.getLogger("dooh.stripe")
router = APIRouter(prefix="/api/stripe", tags=["stripe"])

MAX_EVENT_BYTES = 1 << 20


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not settings.stripe_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stripe webhook isn't set up on this server.")
    payload = await request.body()
    if len(payload) > MAX_EVENT_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Event too large")
    try:
        payments.verify_signature(payload, stripe_signature, settings.stripe_webhook_secret)
        event = json.loads(payload)
    except (payments.BadSignature, ValueError) as e:
        log.warning("Rejected Stripe webhook: %s", e)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe signature") from e
    payment = payments.record_event(db, event)
    if payment:
        log.info("Stripe %s: order %s is %s", event.get("type"), payment.client_reference_id, payment.status.value)
    return {"received": True}
