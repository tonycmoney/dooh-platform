"""Stripe webhook: verified payment confirmations matched to website orders."""

import hashlib
import hmac
import json
import time

import pytest

from app import payments

SECRET = "whsec_test_secret"
KEY = {"Authorization": "Bearer " + "w" * 40}
ORDER_ID = "LFA_1791700000000_ABCD"


def signed(body: dict, secret: str = SECRET, at: int | None = None) -> tuple[bytes, dict]:
    payload = json.dumps(body).encode()
    t = at or int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, {"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"}


def event(type_: str, session_id="cs_live_1", ref=ORDER_ID, payment_status="paid", amount=7000):
    return {"id": f"evt_{type_}_{session_id}", "type": type_, "livemode": True, "data": {"object": {
        "object": "checkout.session", "id": session_id, "client_reference_id": ref,
        "payment_status": payment_status, "amount_total": amount, "currency": "usd",
        "customer_details": {"email": "maria@example.com"}}}}


def send(client, body, **kw):
    payload, headers = signed(body, **kw)
    return client.post("/api/stripe/webhook", content=payload, headers=headers)


def place_order(client, order_id=ORDER_ID):
    res = client.post("/api/website/orders", headers=KEY, json={
        "order_id": order_id, "business_name": "Mercato", "email": "maria@example.com",
        "plan": "tablet-1", "ad_choice": "Design it for me"})
    assert res.status_code in (200, 201)


def order_payment(admin, order_id=ORDER_ID):
    o = next(o for o in admin.get("/api/admin/orders").json() if o["external_id"] == order_id)
    return o["payment_status"], o["paid_amount"], o["paid_currency"]


def test_paid_checkout_marks_the_order_paid(client, admin):
    place_order(client)
    assert order_payment(admin) == ("awaiting", None, None)
    assert send(client, event("checkout.session.completed")).json() == {"received": True}
    assert order_payment(admin) == ("paid", 7000, "USD")


def test_payment_that_arrives_before_the_order(client, admin):
    send(client, event("checkout.session.completed"))
    place_order(client)
    assert order_payment(admin)[0] == "paid"


def test_bank_payment_pending_then_cleared(client, admin):
    place_order(client)
    send(client, event("checkout.session.completed", payment_status="unpaid"))
    assert order_payment(admin)[0] == "pending"
    send(client, event("checkout.session.async_payment_succeeded"))
    assert order_payment(admin)[0] == "paid"


def test_failed_bank_payment(client, admin):
    place_order(client)
    send(client, event("checkout.session.completed", payment_status="unpaid"))
    send(client, event("checkout.session.async_payment_failed"))
    assert order_payment(admin)[0] == "failed"


def test_abandoned_checkout_then_retry_paid(client, admin):
    place_order(client)
    send(client, event("checkout.session.expired", session_id="cs_1", payment_status="unpaid"))
    assert order_payment(admin)[0] == "abandoned"
    assert admin.get("/api/admin/stats").json()["orders_to_review"] == 0  # doesn't nag
    send(client, event("checkout.session.completed", session_id="cs_2"))
    assert order_payment(admin)[0] == "paid"
    assert admin.get("/api/admin/stats").json()["orders_to_review"] == 1


def test_replays_and_out_of_order_events_never_downgrade(client, admin):
    place_order(client)
    for _ in range(2):
        send(client, event("checkout.session.completed"))
    send(client, event("checkout.session.expired", payment_status="unpaid"))  # late, stale
    assert order_payment(admin)[0] == "paid"


def test_other_events_are_acknowledged_and_ignored(client, admin):
    place_order(client)
    res = send(client, {"id": "evt_x", "type": "invoice.paid", "data": {"object": {"object": "invoice", "id": "in_1"}}})
    assert res.status_code == 200 and order_payment(admin)[0] == "awaiting"


@pytest.mark.parametrize("problem", ["wrong_secret", "tampered", "old", "missing"])
def test_forged_or_replayed_events_are_rejected(client, admin, problem):
    place_order(client)
    body = event("checkout.session.completed")
    if problem == "wrong_secret":
        payload, headers = signed(body, secret="whsec_attacker")
    elif problem == "old":
        payload, headers = signed(body, at=int(time.time()) - 600)
    else:
        payload, headers = signed(body)
        if problem == "tampered":
            payload = payload.replace(b"7000", b"1")
        else:
            headers.pop("Stripe-Signature")
    assert client.post("/api/stripe/webhook", content=payload, headers=headers).status_code == 400
    assert order_payment(admin)[0] == "awaiting"


def test_turned_off_without_a_secret(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    assert send(client, event("checkout.session.completed")).status_code == 503


def test_signature_header_with_several_signatures():
    payload = b'{"a":1}'
    t = int(time.time())
    good = hmac.new(SECRET.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    payments.verify_signature(payload, f"t={t},v1={'0' * 64},v1={good},v0=abc", SECRET)
