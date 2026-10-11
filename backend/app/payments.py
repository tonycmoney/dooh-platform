"""Stripe payment confirmations for website orders.

The website's Stripe Payment Links carry the order ID as client_reference_id.
Stripe calls POST /api/stripe/webhook when a checkout completes, its bank
payment clears or fails, or it expires unpaid (after 24 hours). Each session's
outcome is stored and matched to the order by that ID, so it works whichever
arrives first: the order from the website or the payment from Stripe.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PAYMENT_PRECEDENCE, PaymentStatus, StripePayment

SIGNATURE_TOLERANCE_SECONDS = 300

# checkout.session.* event -> status ("completed" depends on payment_status).
EVENT_STATUS = {
    "checkout.session.async_payment_succeeded": PaymentStatus.paid,
    "checkout.session.async_payment_failed": PaymentStatus.failed,
    "checkout.session.expired": PaymentStatus.expired,
}


class BadSignature(Exception):
    pass


def verify_signature(payload: bytes, header: str | None, secret: str, now: float | None = None) -> None:
    """Checks Stripe's `Stripe-Signature` header (t=...,v1=...). Raises
    BadSignature if it doesn't match or is older than 5 minutes (replay)."""
    if not header:
        raise BadSignature("missing Stripe-Signature header")
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        key, _, value = item.strip().partition("=")
        parts.setdefault(key, []).append(value)
    try:
        timestamp = int(parts["t"][0])
    except (KeyError, ValueError) as e:
        raise BadSignature("no timestamp") from e
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
        raise BadSignature("signature doesn't match")
    if abs((now or time.time()) - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        raise BadSignature("timestamp too old")


def status_for(event_type: str, session: dict) -> PaymentStatus | None:
    if event_type == "checkout.session.completed":
        return PaymentStatus.paid if session.get("payment_status") in ("paid", "no_payment_required") else PaymentStatus.pending
    return EVENT_STATUS.get(event_type)


def record_event(db: Session, event: dict) -> StripePayment | None:
    """Stores a checkout.session.* event. Replays and out-of-order events are
    safe: a session's status only moves up (expired < pending < failed < paid)."""
    session = (event.get("data") or {}).get("object") or {}
    status = status_for(event.get("type", ""), session)
    if status is None or session.get("object") != "checkout.session" or not session.get("id"):
        return None
    payment = db.get(StripePayment, session["id"])
    if payment is None:
        payment = StripePayment(session_id=session["id"], status=status)
        db.add(payment)
    elif PAYMENT_PRECEDENCE[status] < PAYMENT_PRECEDENCE[payment.status]:
        return payment
    payment.status = status
    payment.client_reference_id = session.get("client_reference_id") or payment.client_reference_id
    payment.amount_total = session.get("amount_total", payment.amount_total)
    payment.currency = (session.get("currency") or payment.currency or "").upper() or None
    payment.customer_email = (session.get("customer_details") or {}).get("email") or payment.customer_email
    payment.livemode = bool(event.get("livemode", True))
    db.commit()
    return payment


@dataclass
class OrderPayment:
    status: str  # paid | pending | failed | abandoned | awaiting
    amount_total: int | None = None
    currency: str | None = None
    paid_at: object | None = None


def payments_by_order(db: Session, order_ids: list[str]) -> dict[str, OrderPayment]:
    """The best payment outcome for each order ID (a customer may have tried
    checkout more than once)."""
    best: dict[str, StripePayment] = {}
    if order_ids:
        for p in db.scalars(select(StripePayment).where(StripePayment.client_reference_id.in_(order_ids))):
            current = best.get(p.client_reference_id)
            if current is None or PAYMENT_PRECEDENCE[p.status] > PAYMENT_PRECEDENCE[current.status]:
                best[p.client_reference_id] = p
    result = {}
    for order_id in order_ids:
        p = best.get(order_id)
        if p is None:
            result[order_id] = OrderPayment("awaiting")
        else:
            label = "abandoned" if p.status is PaymentStatus.expired else p.status.value
            result[order_id] = OrderPayment(label, p.amount_total, p.currency,
                                            p.updated_at if p.status is PaymentStatus.paid else None)
    return result
