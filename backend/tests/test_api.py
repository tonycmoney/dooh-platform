import io
import uuid
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import Device
from tests.conftest import pair_device

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_requires_login(client):
    assert client.get("/api/admin/screens").status_code == 401
    assert client.post("/api/admin/login", json={"password": "nope"}).status_code == 401


def test_pairing_flow(client, admin):
    reg = client.post("/api/player/register", json={"device_uid": "tab-1"}).json()
    assert len(reg["pairing_code"]) == 6

    creds = {"device_uid": "tab-1", "claim_secret": reg["claim_secret"]}
    assert client.post("/api/player/pairing-status", json=creds).json() == {
        "paired": False, "token": None, "device_id": None, "name": None, "venue_name": None,
    }
    # Wrong secret can't steal the token
    bad = {"device_uid": "tab-1", "claim_secret": "guess"}
    assert client.post("/api/player/pairing-status", json=bad).status_code == 404

    res = admin.post("/api/admin/screens/pair", json={
        "pairing_code": reg["pairing_code"].lower(), "name": "Front", "venue_name": "Gym", "venue_address": "2 Elm"})
    assert res.status_code == 200, res.text

    status = client.post("/api/player/pairing-status", json=creds).json()
    assert status["paired"] and status["token"] and status["name"] == "Front"
    # Token is handed over only once
    assert client.post("/api/player/pairing-status", json=creds).status_code == 404
    assert client.get("/api/player/manifest", headers=auth(status["token"])).status_code == 200

    assert admin.post("/api/admin/screens/pair", json={
        "pairing_code": "ZZZZZZ", "name": "x", "venue_name": "y"}).status_code == 404


def test_reregister_keeps_identity(client, admin):
    token, device_id = pair_device(admin, uid="same")
    reg = client.post("/api/player/register", json={"device_uid": "same"}).json()
    assert client.get("/api/player/manifest", headers=auth(token)).status_code == 401  # old token revoked
    admin.post("/api/admin/screens/pair", json={"pairing_code": reg["pairing_code"], "name": "Again", "venue_name": "V"})
    status = client.post("/api/player/pairing-status", json={"device_uid": "same", "claim_secret": reg["claim_secret"]}).json()
    assert status["device_id"] == device_id


def test_media_loop_manifest_and_assignment(client, admin):
    img = admin.post("/api/admin/media", files={"file": ("ad.png", io.BytesIO(PNG), "image/png")}).json()
    assert img["kind"] == "image" and img["status"] == "approved"
    slide = admin.post("/api/admin/text-slides", json={
        "title": "Promo", "text": "50% off", "font_size": 120, "text_color": "#FFFF00", "background_color": "#000080"}).json()
    assert admin.post("/api/admin/media", files={"file": ("x.gif", b"GIF89a", "image/gif")}).status_code == 400

    loop = admin.post("/api/admin/loops", json={"name": "Main", "items": [
        {"media_id": img["id"]}, {"media_id": slide["id"], "duration_seconds": 5}]}).json()
    assert [i["duration_seconds"] for i in loop["items"]] == [10, 5]  # default 10 s

    token, device_id = pair_device(admin)
    empty = client.get("/api/player/manifest", headers=auth(token)).json()
    assert empty["items"] == []

    admin.put(f"/api/admin/loops/{loop['id']}/screens", json={"device_ids": [device_id]})
    m1 = client.get("/api/player/manifest", headers=auth(token)).json()
    assert [i["kind"] for i in m1["items"]] == ["image", "text"]
    assert m1["items"][0]["url"].startswith("/files/") and m1["items"][0]["sha256"]
    assert m1["items"][1]["text"]["text"] == "50% off"
    assert client.get(m1["items"][0]["url"]).content == PNG

    # Reorder -> version changes
    admin.put(f"/api/admin/loops/{loop['id']}", json={"name": "Main", "items": [
        {"media_id": slide["id"], "duration_seconds": 5}, {"media_id": img["id"]}]})
    m2 = client.get("/api/player/manifest", headers=auth(token)).json()
    assert m2["version"] != m1["version"] and m2["items"][0]["kind"] == "text"

    hb = client.post("/api/player/heartbeat", headers=auth(token), json={"manifest_version": m2["version"]}).json()
    assert hb["manifest_version"] == m2["version"]

    # Unassign
    admin.put(f"/api/admin/loops/{loop['id']}/screens", json={"device_ids": []})
    assert client.get("/api/player/manifest", headers=auth(token)).json()["items"] == []


def test_approval_queue_filters_manifest(client, admin):
    admin.put("/api/admin/settings", json={"auto_approve": False})
    slide = admin.post("/api/admin/text-slides", json={"title": "T", "text": "hi"}).json()
    assert slide["status"] == "pending"
    loop = admin.post("/api/admin/loops", json={"name": "L", "items": [{"media_id": slide["id"]}]}).json()
    token, device_id = pair_device(admin, loop_id=loop["id"])
    assert client.get("/api/player/manifest", headers=auth(token)).json()["items"] == []
    assert len(admin.get("/api/admin/media?status=pending").json()) == 1
    admin.post(f"/api/admin/media/{slide['id']}/approve")
    assert len(client.get("/api/player/manifest", headers=auth(token)).json()["items"]) == 1


def test_proof_of_play_is_idempotent(client, admin):
    token, device_id = pair_device(admin)
    play = {"id": str(uuid.uuid4()), "media_title": "Ad", "started_at": datetime.now(timezone.utc).isoformat(), "duration_ms": 10000}
    first = client.post("/api/player/plays", headers=auth(token), json={"plays": [play]}).json()
    again = client.post("/api/player/plays", headers=auth(token), json={"plays": [play]}).json()
    assert first["inserted"] == 1 and again["inserted"] == 0
    assert again["accepted"] == [play["id"]]
    assert len(admin.get(f"/api/admin/screens/{device_id}/plays").json()) == 1


def test_heartbeat_and_offline_after_three_missed(client, admin):
    token, device_id = pair_device(admin)
    screen = admin.get("/api/admin/screens").json()[0]
    assert screen["online"] is False  # never heard from

    client.post("/api/player/heartbeat", headers=auth(token), json={
        "battery_level": 77, "is_charging": True, "latitude": 41.76, "longitude": -72.67,
        "app_version": "1.2.3", "now_playing_title": "Promo"})
    screen = admin.get("/api/admin/screens").json()[0]
    assert screen["online"] and screen["battery_level"] == 77 and screen["latitude"] == 41.76
    assert screen["now_playing_title"] == "Promo" and screen["app_version"] == "1.2.3"

    with SessionLocal() as db:
        db.get(Device, uuid.UUID(device_id)).last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=150)
        db.commit()
    assert admin.get("/api/admin/screens").json()[0]["online"] is True  # 2 missed: still online
    with SessionLocal() as db:
        db.get(Device, uuid.UUID(device_id)).last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=181)
        db.commit()
    assert admin.get("/api/admin/screens").json()[0]["online"] is False


def test_delete_media_removes_from_loops(client, admin):
    slide = admin.post("/api/admin/text-slides", json={"title": "T", "text": "hi"}).json()
    loop = admin.post("/api/admin/loops", json={"name": "L", "items": [{"media_id": slide["id"]}]}).json()
    assert admin.delete(f"/api/admin/media/{slide['id']}").status_code == 204
    assert admin.get(f"/api/admin/loops/{loop['id']}").json()["items"] == []
