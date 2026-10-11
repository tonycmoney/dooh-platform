"""Orders from the customer website: key check, idempotency, safe file
downloads, and the rule that website ads only play once approved."""

import io
from pathlib import Path

import pytest
from PIL import Image

from app import orders
from tests.conftest import pair_device

KEY = {"Authorization": "Bearer " + "w" * 40}
FILE_URL = "https://abcd.supabase.co/storage/v1/object/sign/ad-uploads/LFA_1_ABCD/ad.png?token=x"


def order(**extra):
    return {
        "order_id": "LFA_1791700000000_ABCD",
        "business_name": "Mercato Italian Kitchen",
        "contact_name": "Maria Rossi",
        "email": "maria@example.com",
        "phone": "203-555-0100",
        "plan": "tablet-1",
        "plan_name": "Digital Screen Ad Network: 1 ad spot ($70 per month)",
        "city": "Stamford",
        "ad_choice": "Upload",
        "ad_text": "$10 off dinner",
        **extra,
    }


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1080, 1920), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def fake_storage(monkeypatch):
    """Stands in for Supabase: serves files by URL."""
    files: dict[str, bytes] = {}

    def download(url, target: Path):
        if url not in files:
            raise ValueError("Downloading the file failed (HTTP 400); the link may have expired.")
        target.write_bytes(files[url])

    monkeypatch.setattr(orders, "download", download)
    return files


def test_key_is_required(client):
    assert client.post("/api/website/orders", json=order()).status_code == 401
    bad = {"Authorization": "Bearer " + "x" * 40}
    assert client.post("/api/website/orders", json=order(), headers=bad).status_code == 401


def test_wrong_keys_are_throttled(client):
    bad = {"Authorization": "Bearer nope"}
    for _ in range(20):
        client.post("/api/website/orders", json=order(), headers=bad)
    assert client.post("/api/website/orders", json=order(), headers=KEY).status_code == 429


def test_turned_off_without_a_key(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "website_api_key", "")
    assert client.post("/api/website/orders", json=order(), headers=KEY).status_code == 503


def test_order_with_file_waits_for_approval_then_plays(client, admin, fake_storage):
    fake_storage[FILE_URL] = png()
    admin.put("/api/admin/settings", json={"auto_approve": True})  # must not apply to website ads

    res = client.post("/api/website/orders", json=order(file_url=FILE_URL, file_name="ad.png"), headers=KEY)
    assert res.status_code == 201, res.text
    assert res.json() == {"order_id": "LFA_1791700000000_ABCD", "received": True, "duplicate": False, "file": "queued"}

    [o] = admin.get("/api/admin/orders").json()
    assert o["business_name"] == "Mercato Italian Kitchen" and o["email"] == "maria@example.com"
    assert o["plan"] == "tablet-1" and o["city"] == "Stamford" and o["file_status"] == "ready"
    media = o["media"]
    assert media["status"] == "pending" and (media["width"], media["height"]) == (1080, 1920)
    assert media["title"].startswith("Mercato Italian Kitchen")
    assert admin.get("/api/admin/stats").json()["orders_to_review"] == 1

    # In a loop on a screen, it still doesn't play until approved.
    loop = admin.post("/api/admin/loops", json={"name": "Main", "items": [{"media_id": media["id"]}]}).json()
    token, device_id = pair_device(admin, loop_id=loop["id"])
    manifest = lambda: client.get("/api/player/manifest", headers={"Authorization": f"Bearer {token}"}).json()
    assert manifest()["items"] == []
    admin.post(f"/api/admin/media/{media['id']}/approve")
    assert [i["media_id"] for i in manifest()["items"]] == [media["id"]]
    assert admin.get("/api/admin/stats").json()["orders_to_review"] == 0


def test_same_order_twice_is_stored_once(client, admin, fake_storage):
    fake_storage[FILE_URL] = png()
    first = client.post("/api/website/orders", json=order(file_url=FILE_URL), headers=KEY)
    again = client.post("/api/website/orders", json=order(file_url=FILE_URL), headers=KEY)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["duplicate"] is True and again.json()["file"] == "ready"
    assert len(admin.get("/api/admin/orders").json()) == 1
    assert len(admin.get("/api/admin/media").json()) == 1


@pytest.mark.parametrize("url", [
    "http://abcd.supabase.co/x.png",           # not https
    "https://evil.example.com/x.png",          # other host
    "https://supabase.co.evil.com/x.png",      # look-alike
    "https://user@abcd.supabase.co/x.png",     # credentials trick
    "https://169.254.169.254/latest/meta-data",
])
def test_files_only_from_storage_over_https(client, url):
    res = client.post("/api/website/orders", json=order(file_url=url, file_name="ad.png"), headers=KEY)
    assert res.status_code == 400


def test_unsupported_file_type_is_refused_up_front(client):
    url = FILE_URL.replace("ad.png", "flyer.pdf")
    res = client.post("/api/website/orders", json=order(file_url=url), headers=KEY)
    assert res.status_code == 400 and "PDF isn't supported" in res.json()["detail"]


def test_bad_input_is_rejected(client):
    assert client.post("/api/website/orders", json=order(email="not-an-email"), headers=KEY).status_code == 422
    assert client.post("/api/website/orders", json=order(order_id="bad id!"), headers=KEY).status_code == 422
    assert client.post("/api/website/orders", json=order(business_name=""), headers=KEY).status_code == 422


def test_failed_download_can_be_retried(client, admin, fake_storage):
    client.post("/api/website/orders", json=order(file_url=FILE_URL), headers=KEY)
    [o] = admin.get("/api/admin/orders").json()
    assert o["file_status"] == "failed" and "expired" in o["file_error"] and o["can_retry"]
    assert admin.get("/api/admin/stats").json()["orders_to_review"] == 1

    fake_storage[FILE_URL] = png()
    retried = admin.post(f"/api/admin/orders/{o['id']}/retry")
    assert retried.status_code == 200
    [o] = admin.get("/api/admin/orders").json()
    assert o["file_status"] == "ready" and o["media"]["status"] == "pending"


def test_design_order_gets_its_ad_attached_later(client, admin):
    res = client.post("/api/website/orders", json=order(ad_choice="Design it for me"), headers=KEY)
    assert res.json()["file"] == "none"
    [o] = admin.get("/api/admin/orders").json()
    assert o["media"] is None and admin.get("/api/admin/stats").json()["orders_to_review"] == 1

    attached = admin.post(f"/api/admin/orders/{o['id']}/file", content=png(), headers={"X-Filename": "design.png"})
    assert attached.status_code == 200, attached.text
    assert attached.json()["media"]["status"] == "pending"


def test_delete_order_removes_unapproved_ad(client, admin, fake_storage):
    fake_storage[FILE_URL] = png()
    client.post("/api/website/orders", json=order(file_url=FILE_URL), headers=KEY)
    [o] = admin.get("/api/admin/orders").json()
    assert admin.delete(f"/api/admin/orders/{o['id']}").status_code == 204
    assert admin.get("/api/admin/orders").json() == [] and admin.get("/api/admin/media").json() == []


def test_allowed_host_matching():
    assert orders.allowed_file_host("https://abcd.supabase.co/storage/v1/object/sign/x")
    assert not orders.allowed_file_host("https://abcd.supabase.co.attacker.net/x")
    assert not orders.allowed_file_host("ftp://abcd.supabase.co/x")
