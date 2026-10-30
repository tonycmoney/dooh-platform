"""Trillboards programmatic fill: screens with no paid ads show Trillboards."""

import httpx
import pytest

from app import trillboards
from app.config import settings
from app.db import SessionLocal
from app.models import Device
from tests.conftest import pair_device


class FakeTrillboards:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body if body is not None else {
            "screen_id": "scr_1", "fingerprint": "P_abc123",
            "embed_url": "https://screen.trillboards.com?fp=P_abc123",
        }
        self.calls = []

    def __call__(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append((method, url, json, headers))
        return httpx.Response(self.status, json=self.body, request=httpx.Request(method, url))


@pytest.fixture
def tb(monkeypatch):
    fake = FakeTrillboards()
    monkeypatch.setattr(trillboards.httpx, "request", fake)
    monkeypatch.setattr(settings, "trillboards_api_key", "trb_partner_test")
    monkeypatch.setattr(settings, "trillboards_enabled", True)
    return fake


def beat(client, token, **extra):
    return client.post(
        "/api/player/heartbeat",
        json={"battery_level": 80, "latitude": 41.3, "longitude": -72.9, **extra},
        headers={"Authorization": f"Bearer {token}"},
    )


def manifest(client, token):
    return client.get("/api/player/manifest", headers={"Authorization": f"Bearer {token}"}).json()


def test_off_without_key(admin, client):
    token, device_id = pair_device(admin)
    assert beat(client, token).status_code == 200
    assert manifest(client, token)["fallback_url"] is None
    screen = admin.get("/api/admin/screens").json()[0]
    assert screen["programmatic_status"] == "off"


def test_heartbeat_registers_screen_and_manifest_gets_fallback(admin, client, tb):
    token, device_id = pair_device(admin)
    before = manifest(client, token)
    assert before["fallback_url"] is None

    hb = beat(client, token).json()
    assert len(tb.calls) == 1
    method, url, body, headers = tb.calls[0]
    assert (method, url) == ("POST", "https://api.trillboards.com/v1/partner/device")
    assert headers["Authorization"] == "Bearer trb_partner_test"
    assert body["device_id"] == f"lfa-{device_id}"
    assert body["display"]["orientation"] == "portrait"
    assert body["location"]["lat"] == 41.3 and body["location"]["venue_name"] == "Cafe"

    after = manifest(client, token)
    assert after["fallback_url"] == "https://screen.trillboards.com?fp=P_abc123"
    assert after["items"] == []
    # The version changed, so the tablet's next heartbeat triggers a resync.
    assert after["version"] != before["version"]
    assert beat(client, token).json()["manifest_version"] == after["version"]
    assert hb["manifest_version"] == before["version"]  # registered after replying

    # Registered once only.
    beat(client, token)
    assert len(tb.calls) == 1
    screen = admin.get("/api/admin/screens").json()[0]
    assert screen["programmatic_status"] == "ready"


def test_fingerprint_only_response_builds_embed_url(admin, client, tb):
    tb.body = {"data": {"fingerprint": "P_xyz", "screen_id": "scr_9"}}
    token, _ = pair_device(admin)
    beat(client, token)
    assert manifest(client, token)["fallback_url"] == "https://screen.trillboards.com?fp=P_xyz"


def test_failure_is_shown_and_retried_later(admin, client, tb):
    tb.status, tb.body = 401, {"error": {"message": "Invalid API key"}}
    token, device_id = pair_device(admin)
    beat(client, token)
    beat(client, token)
    assert len(tb.calls) == 1  # backoff, not every heartbeat
    screen = admin.get("/api/admin/screens").json()[0]
    assert screen["programmatic_status"] == "error"
    assert screen["programmatic_error"] == "Invalid API key"
    assert manifest(client, token)["fallback_url"] is None

    with SessionLocal() as db:
        d = db.get(Device, device_id)
        d.trillboards_attempted_at = d.trillboards_attempted_at - trillboards.RETRY_AFTER
        db.commit()
    tb.status, tb.body = 200, FakeTrillboards().body
    beat(client, token)
    assert len(tb.calls) == 2
    assert manifest(client, token)["fallback_url"]


def test_screen_can_turn_fill_off(admin, client, tb):
    token, device_id = pair_device(admin)
    beat(client, token)
    assert manifest(client, token)["fallback_url"]
    r = admin.patch(f"/api/admin/screens/{device_id}", json={"programmatic_fill": False})
    assert r.json()["programmatic_status"] == "off"
    assert manifest(client, token)["fallback_url"] is None
    admin.patch(f"/api/admin/screens/{device_id}", json={"programmatic_fill": True})
    assert manifest(client, token)["fallback_url"]


def test_programmatic_plays_are_logged_without_media(admin, client, tb):
    token, device_id = pair_device(admin)
    r = client.post(
        "/api/player/plays",
        json={"plays": [{
            "id": "11111111-1111-4111-8111-111111111111",
            "media_id": None,
            "media_title": "Trillboards programmatic",
            "started_at": "2026-10-30T17:00:00Z",
            "duration_ms": 15000,
        }]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.json()["inserted"] == 1
