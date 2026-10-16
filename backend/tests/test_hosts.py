"""Hosts: revenue per screen, the host's private page, and Stripe payouts."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app import host_revenue, stripe_api
from app.config import settings
from app.db import SessionLocal
from app.models import AdPayment, Media, MediaKind, PlayLog, StripePayment, PaymentStatus, WebsiteOrder

from .conftest import pair_device
from .test_stripe import send

NOW = datetime.now(timezone.utc)
THIS_MONTH = host_revenue.current_month()
LAST_MONTH = host_revenue.recent_months(THIS_MONTH, 2)[1]


def mid(month: date) -> datetime:
    start, end = host_revenue.month_bounds(month)
    return min(start + (end - start) / 2, NOW - timedelta(minutes=1)) if month == THIS_MONTH else start + (end - start) / 2


def advertiser(title="Mercato ad", sub="sub_1", order_id="LFA_1"):
    """An ad from a paid website order whose subscription is `sub`."""
    with SessionLocal() as db:
        media = Media(kind=MediaKind.image, title=title)
        db.add(media)
        db.flush()
        db.add(WebsiteOrder(external_id=order_id, business_name=title, email="a@example.com",
                            plan="bundle", media_id=media.id))
        db.add(StripePayment(session_id=f"cs_{order_id}", client_reference_id=order_id,
                             status=PaymentStatus.paid, subscription_id=sub))
        db.commit()
        return media.id


def paid(sub, cents, at, invoice=None):
    with SessionLocal() as db:
        db.add(AdPayment(invoice_id=invoice or f"in_{uuid.uuid4().hex}", subscription_id=sub, amount=cents,
                         paid_at=at))
        db.commit()


def played(device_id, media_id, seconds, at):
    with SessionLocal() as db:
        db.add(PlayLog(id=uuid.uuid4(), device_id=uuid.UUID(device_id), media_id=media_id, media_title="ad",
                       started_at=at, duration_ms=seconds * 1000))
        db.commit()


def make_host(admin, **kw):
    res = admin.post("/api/admin/hosts", json={"name": "Joe", "business_name": "Joe's Barbershop",
                                                "email": "joe@example.com", **kw})
    assert res.status_code == 201, res.text
    return res.json()


def token_of(host):
    return host["link"].rsplit("/", 1)[1]


def test_new_host_gets_20_percent_and_a_private_link(admin):
    host = make_host(admin)
    assert host["share_percent"] == 20
    assert "/host/" in host["link"] and len(token_of(host)) >= 40
    assert host["payout_status"] == "not_started"


def test_revenue_is_split_by_play_time_and_host_earns_its_share(client, admin):
    _, screen_a = pair_device(admin, uid="tablet-a")
    _, screen_b = pair_device(admin, uid="tablet-b")
    ad = advertiser()
    paid("sub_1", 35000, mid(LAST_MONTH))
    played(screen_a, ad, 300, mid(LAST_MONTH))  # 3/4 of the ad's play time
    played(screen_b, ad, 100, mid(LAST_MONTH))
    host = make_host(admin)
    admin.put(f"/api/admin/hosts/{host['id']}/screens", json={"device_ids": [screen_a]})

    month = admin.get(f"/api/admin/hosts/{host['id']}/months/{LAST_MONTH}").json()
    assert month["revenue"] == 26250  # $262.50 of the $350
    assert month["earnings"] == 5250  # 20% = $52.50
    assert month["screens"][0]["plays"] == 1 and month["screens"][0]["seconds"] == 300

    page = client.get(f"/api/host/{token_of(host)}", params={"month": str(LAST_MONTH)}).json()
    assert page["business_name"] == "Joe's Barbershop"
    assert page["month"]["earnings"] == 5250
    assert len(page["history"]) == 6


def test_payments_outside_the_month_and_unplayed_ads_dont_count(client, admin):
    _, screen = pair_device(admin)
    ad = advertiser()
    advertiser(title="Never played", sub="sub_2", order_id="LFA_2")
    paid("sub_1", 35000, mid(LAST_MONTH))
    paid("sub_2", 35000, mid(LAST_MONTH))
    played(screen, ad, 60, mid(THIS_MONTH))  # played this month, paid last month
    host = make_host(admin)
    admin.put(f"/api/admin/hosts/{host['id']}/screens", json={"device_ids": [screen]})
    assert admin.get(f"/api/admin/hosts/{host['id']}/months/{LAST_MONTH}").json()["revenue"] == 0


def test_bad_or_reset_link_is_refused(client, admin):
    host = make_host(admin)
    assert client.get("/api/host/not-a-real-token-at-all-xyz").status_code == 404
    old = token_of(host)
    new = admin.post(f"/api/admin/hosts/{host['id']}/reset-link").json()
    assert client.get(f"/api/host/{old}").status_code == 404
    assert client.get(f"/api/host/{token_of(new)}").status_code == 200


def test_invoice_webhook_records_only_recurring_lines(client):
    event = {"id": "evt_inv", "type": "invoice.paid", "livemode": True, "created": int(NOW.timestamp()),
             "data": {"object": {"object": "invoice", "id": "in_1", "currency": "usd",
                                 "parent": {"subscription_details": {"subscription": "sub_9"}},
                                 "status_transitions": {"paid_at": int(NOW.timestamp())},
                                 "lines": {"data": [
                                     {"amount": 35000, "parent": {"type": "subscription_item_details"}},
                                     {"amount": 15000, "parent": {"type": "invoice_item_details"}},
                                 ]}}}}
    assert send(client, event).status_code == 200
    assert send(client, event).status_code == 200  # replay is harmless
    with SessionLocal() as db:
        row = db.get(AdPayment, "in_1")
        assert (row.subscription_id, row.amount) == ("sub_9", 35000)


def test_checkout_records_its_subscription(client):
    event = {"id": "evt_cs", "type": "checkout.session.completed", "livemode": True, "data": {"object": {
        "object": "checkout.session", "id": "cs_9", "client_reference_id": "LFA_9", "payment_status": "paid",
        "amount_total": 50000, "currency": "usd", "subscription": "sub_9"}}}
    send(client, event)
    with SessionLocal() as db:
        assert db.get(StripePayment, "cs_9").subscription_id == "sub_9"


@pytest.fixture
def fake_stripe(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(stripe_api, "create_express_account", lambda *a: calls.append("account") or "acct_1")
    monkeypatch.setattr(stripe_api, "onboarding_link", lambda *a, **k: "https://connect.stripe.com/setup/x")
    monkeypatch.setattr(stripe_api, "payouts_ready", lambda acct: True)
    monkeypatch.setattr(stripe_api, "create_transfer",
                        lambda **k: calls.append(("transfer", k["amount"], k["idempotency_key"])) or "tr_1")
    return calls


def test_payout_setup_and_monthly_payout(client, admin, fake_stripe):
    _, screen = pair_device(admin)
    ad = advertiser()
    paid("sub_1", 35000, mid(LAST_MONTH))
    played(screen, ad, 60, mid(LAST_MONTH))
    host = make_host(admin)
    admin.put(f"/api/admin/hosts/{host['id']}/screens", json={"device_ids": [screen]})
    token = token_of(host)

    pay = lambda m: admin.post(f"/api/admin/hosts/{host['id']}/payouts", json={"month": str(m)})
    assert pay(LAST_MONTH).status_code == 400  # not set up yet

    assert client.post(f"/api/host/{token}/payout-setup").json()["url"].startswith("https://connect.stripe.com")
    assert client.get(f"/api/host/{token}").json()["payout_status"] == "ready"

    assert pay(THIS_MONTH).status_code == 400  # month not finished
    res = pay(LAST_MONTH)
    assert res.status_code == 201 and res.json()["amount"] == 7000  # 20% of $350
    assert pay(LAST_MONTH).status_code == 409  # only once
    assert fake_stripe == ["account", ("transfer", 7000, f"host-payout-{host['id']}-{LAST_MONTH}")]
    assert client.get(f"/api/host/{token}").json()["payouts"][0]["amount"] == 7000


def test_payout_setup_without_stripe_key_is_a_friendly_error(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    host = make_host(admin)
    res = client.post(f"/api/host/{token_of(host)}/payout-setup")
    assert res.status_code == 503 and client.get(f"/api/host/{token_of(host)}").json()["payouts_available"] is False


def test_assigning_a_screen_moves_it_between_hosts(admin):
    _, screen = pair_device(admin)
    a, b = make_host(admin), make_host(admin, business_name="Suds Laundromat")
    admin.put(f"/api/admin/hosts/{a['id']}/screens", json={"device_ids": [screen]})
    admin.put(f"/api/admin/hosts/{b['id']}/screens", json={"device_ids": [screen]})
    hosts = {h["business_name"]: h["device_ids"] for h in admin.get("/api/admin/hosts").json()}
    assert hosts == {"Joe's Barbershop": [], "Suds Laundromat": [screen]}


def test_host_endpoints_need_admin_login(client):
    assert client.get("/api/admin/hosts").status_code == 401
