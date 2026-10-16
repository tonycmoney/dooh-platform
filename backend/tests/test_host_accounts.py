"""Host accounts used by the website's Host Sign In pages."""

import pytest
from fastapi.testclient import TestClient

from app import stripe_api
from app.config import settings
from app.main import app

from .conftest import pair_device

KEY = {"Authorization": "Bearer " + "w" * 40}
BASE = "/api/website/hosts"


@pytest.fixture
def site():
    c = TestClient(app)
    c.headers.update(KEY)
    return c


def register(site, email="Joe@Example.com", business="Joe's Barbershop"):
    return site.post(f"{BASE}/register", json={"email": email, "name": "Joe", "business_name": business})


def tablet_code(uid="tablet-1"):
    return TestClient(app).post("/api/player/register", json={"device_uid": uid, "app_version": "1.0.0"}).json()


def test_needs_the_website_key(client):
    assert client.post(f"{BASE}/account", json={"email": "joe@example.com"}).status_code == 401


def test_sign_up_then_sign_in_by_email(site):
    assert site.post(f"{BASE}/account", json={"email": "joe@example.com"}).json()["detail"] == "no_host"
    res = register(site)
    assert res.status_code == 201
    assert res.json()["share_percent"] == 20 and res.json()["email"] == "joe@example.com"
    assert register(site).status_code == 200  # same email again: same host
    page = site.post(f"{BASE}/account", json={"email": "JOE@example.com"}).json()
    assert page["business_name"] == "Joe's Barbershop" and len(page["history"]) == 6


def test_host_adds_as_many_tablets_as_they_want(site, admin):
    _, loop_screen = pair_device(admin, uid="existing")  # puts the network loop on a screen
    loop = admin.post("/api/admin/loops", json={"name": "Network"}).json()
    admin.put(f"/api/admin/loops/{loop['id']}/screens", json={"device_ids": [loop_screen]})
    register(site)
    for i in range(3):
        code = tablet_code(f"tablet-{i}")["pairing_code"]
        res = site.post(f"{BASE}/tablets", json={"email": "joe@example.com", "pairing_code": code.lower(),
                                                 "name": f"Counter {i}"})
        assert res.status_code == 201, res.text
    screens = res.json()["month"]["screens"]
    assert sorted(s["name"] for s in screens) == ["Counter 0", "Counter 1", "Counter 2"]
    paired = {s["name"]: s for s in admin.get("/api/admin/screens").json()}
    assert paired["Counter 0"]["venue_name"] == "Joe's Barbershop"
    assert paired["Counter 0"]["loop_id"] == loop["id"]  # joins the network
    host = admin.get("/api/admin/hosts").json()[0]
    assert len(host["device_ids"]) == 3


def test_wrong_code_or_unknown_host(site):
    register(site)
    res = site.post(f"{BASE}/tablets", json={"email": "joe@example.com", "pairing_code": "ZZZZZZ", "name": "X"})
    assert res.status_code == 404 and "code" in res.json()["detail"]
    code = tablet_code()["pairing_code"]
    res = site.post(f"{BASE}/tablets", json={"email": "nobody@example.com", "pairing_code": code, "name": "X"})
    assert res.status_code == 404


def test_hosts_only_see_their_own_tablets(site):
    register(site)
    register(site, email="sue@example.com", business="Suds Laundromat")
    code = tablet_code()["pairing_code"]
    site.post(f"{BASE}/tablets", json={"email": "joe@example.com", "pairing_code": code, "name": "Front"})
    sue = site.post(f"{BASE}/account", json={"email": "sue@example.com"}).json()
    assert sue["month"]["screens"] == []


def test_payout_setup_returns_to_the_website(site, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(stripe_api, "create_express_account", lambda *a: "acct_1")
    seen = {}
    monkeypatch.setattr(stripe_api, "onboarding_link",
                        lambda acct, refresh_url, return_url: seen.update(r=return_url) or "https://connect.stripe.com/x")
    register(site)
    bad = site.post(f"{BASE}/payout-setup", json={"email": "joe@example.com", "return_url": "https://evil.com/x"})
    assert bad.status_code == 400
    ok = site.post(f"{BASE}/payout-setup", json={"email": "joe@example.com",
                                                 "return_url": "https://connecticut-flyer-flow.lovable.app/host-dashboard"})
    assert ok.json()["url"].startswith("https://connect.stripe.com")
    assert seen["r"] == "https://connecticut-flyer-flow.lovable.app/host-dashboard?setup=done"


def test_admin_cant_give_two_hosts_one_email(admin):
    body = {"name": "Joe", "business_name": "A", "email": "joe@example.com"}
    assert admin.post("/api/admin/hosts", json=body).status_code == 201
    assert admin.post("/api/admin/hosts", json={**body, "email": "JOE@example.com"}).status_code == 409
