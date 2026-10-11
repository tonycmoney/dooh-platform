"""Maintenance PIN for the tablets' hidden panel, and swapping a tablet."""

import base64
import hashlib
import uuid
from datetime import datetime, timezone

from tests.conftest import pair_device


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_maintenance_pin_reaches_tablets_as_a_hash(client, admin):
    token, _ = pair_device(admin)
    assert admin.get("/api/admin/settings").json()["maintenance_pin_set"] is False
    assert client.post("/api/player/heartbeat", headers=auth(token), json={}).json()["maintenance_pin"] is None

    for bad in ("12", "123456789", "12ab", ""):
        assert admin.put("/api/admin/maintenance-pin", json={"pin": bad}).status_code == 422
    assert admin.put("/api/admin/maintenance-pin", json={"pin": "4821"}).json()["maintenance_pin_set"] is True

    pin = client.post("/api/player/heartbeat", headers=auth(token), json={}).json()["maintenance_pin"]
    assert "4821" not in str(pin)
    expected = hashlib.pbkdf2_hmac("sha256", b"4821", base64.b64decode(pin["salt"]), pin["iterations"])
    assert expected.hex() == pin["hash"] and pin["iterations"] >= 100_000
    wrong = hashlib.pbkdf2_hmac("sha256", b"0000", base64.b64decode(pin["salt"]), pin["iterations"])
    assert wrong.hex() != pin["hash"]

    assert admin.delete("/api/admin/maintenance-pin").json()["maintenance_pin_set"] is False
    assert client.post("/api/player/heartbeat", headers=auth(token), json={}).json()["maintenance_pin"] is None


def test_pin_endpoints_need_login(client):
    assert client.put("/api/admin/maintenance-pin", json={"pin": "1234"}).status_code == 401


def test_new_tablet_replaces_a_screen_keeping_its_history(client, admin):
    loop = admin.post("/api/admin/loops", json={"name": "Main", "items": []}).json()
    old_token, old_id = pair_device(admin, uid="android-old", loop_id=loop["id"])
    client.post("/api/player/plays", headers=auth(old_token), json={"plays": [
        {"id": str(uuid.uuid4()), "media_title": "Ad", "started_at": datetime.now(timezone.utc).isoformat(),
         "duration_ms": 10000}]})

    new_token, new_id = pair_device(admin, uid="android-new", name="Lobby", replaces_device_id=old_id)
    screens = admin.get("/api/admin/screens").json()
    assert [s["id"] for s in screens] == [new_id]
    assert screens[0]["loop_id"] == loop["id"]  # loop carried over
    assert [p["media_title"] for p in admin.get(f"/api/admin/screens/{new_id}/plays").json()] == ["Ad"]
    assert client.get("/api/player/manifest", headers=auth(old_token)).status_code == 401
    assert client.get("/api/player/manifest", headers=auth(new_token)).status_code == 200
