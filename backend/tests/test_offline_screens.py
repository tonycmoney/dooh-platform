"""Offline screens (no WiFi at the venue on purpose), WiFi outages the
tablet logs itself, and the visit list."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import reports
from app.db import SessionLocal
from app.models import AlertKind, ConnectionMode, Device, DeviceOutage
from tests.conftest import pair_device
from tests.test_monitoring import NOW, outbox, run, screen, set_seen  # noqa: F401


def set_mode(admin, device_id, mode):
    r = admin.patch(f"/api/admin/screens/{device_id}", json={"connection_mode": mode})
    assert r.status_code == 200, r.text
    return r.json()


def test_screens_start_on_wifi_and_can_be_switched(admin):
    _, device_id = pair_device(admin)
    screen = admin.get("/api/admin/screens").json()[0]
    assert screen["connection_mode"] == "wifi" and screen["needs_visit"] is False
    assert "programmatic_fill" not in screen
    assert set_mode(admin, device_id, "offline")["connection_mode"] == "offline"
    assert admin.patch(f"/api/admin/screens/{device_id}", json={"connection_mode": "cellular"}).status_code == 422


def test_pair_straight_into_offline_mode(admin):
    _, device_id = pair_device(admin, connection_mode="offline")
    with SessionLocal() as db:
        assert db.get(Device, uuid.UUID(device_id)).connection_mode is ConnectionMode.offline


def test_offline_screen_never_sends_offline_alerts(admin, outbox):
    d = screen(admin, seen_ago=timedelta(days=2))
    set_mode(admin, d, "offline")
    assert run() == [] and outbox == []


def test_switching_to_offline_closes_open_alert_quietly(admin, outbox):
    d = screen(admin, seen_ago=timedelta(minutes=30))
    [a] = run()
    assert a.kind == AlertKind.offline and len(outbox) == 1
    set_mode(admin, d, "offline")
    [a] = run(NOW + timedelta(minutes=1))
    assert a.resolved_at is not None
    assert len(outbox) == 1  # no "back online" email: it isn't


def test_sync_overdue_alert_and_recovery(admin, outbox):
    d = screen(admin, paired_ago=timedelta(days=20), seen_ago=timedelta(days=6))
    set_mode(admin, d, "offline")
    assert run() == []

    set_seen(d, NOW - timedelta(days=8))
    [a] = run()
    assert a.kind == AlertKind.sync_overdue
    assert outbox[-1][0] == "⚠ Lobby needs a visit"
    assert "hotspot" in outbox[-1][1]

    set_seen(d, NOW + timedelta(minutes=1))
    [a] = run(NOW + timedelta(minutes=2))
    assert a.resolved_at is not None and outbox[-1][0] == "✓ Lobby is synced"


def test_wifi_screens_never_get_sync_overdue(admin, outbox):
    screen(admin, seen_ago=timedelta(days=9))
    kinds = {a.kind for a in run()}
    assert AlertKind.sync_overdue not in kinds and AlertKind.offline in kinds


def test_visit_reasons(admin):
    d = screen(admin, paired_ago=timedelta(days=20), seen_ago=timedelta(days=9))
    set_mode(admin, d, "offline")
    s = admin.get("/api/admin/screens").json()[0]
    # Never reported a manifest, so its ads are out of date too.
    assert s["needs_visit"] is True
    assert s["visit_reasons"][0] == "New ads to load"
    assert s["visit_reasons"][1].startswith("Not synced in")


def test_visit_after_a_week_offline_does_not_page_not_playing(admin, outbox):
    """Comes back on the hotspot: its saved plays haven't uploaded yet, but
    that's no reason to say it stopped playing."""
    d = screen(admin, paired_ago=timedelta(days=20), seen_ago=timedelta(days=6), played_ago=timedelta(days=6))
    set_mode(admin, d, "offline")
    with SessionLocal() as db:
        dev = db.get(Device, d)
        dev.last_seen_at = dev.connected_since = NOW
        db.commit()
    assert run() == [] and outbox == []


def test_heartbeat_starts_a_new_connected_stretch_after_a_gap(admin, client):
    token, device_id = pair_device(admin)
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/player/heartbeat", json={}, headers=headers)
    with SessionLocal() as db:
        first = db.get(Device, uuid.UUID(device_id)).connected_since
        assert first is not None
    client.post("/api/player/heartbeat", json={}, headers=headers)
    with SessionLocal() as db:
        dev = db.get(Device, uuid.UUID(device_id))
        assert dev.connected_since == first  # still the same stretch
        dev.last_seen_at = datetime.now(timezone.utc) - timedelta(hours=3)
        db.commit()
    client.post("/api/player/heartbeat", json={}, headers=headers)
    with SessionLocal() as db:
        assert db.get(Device, uuid.UUID(device_id)).connected_since > first


def test_tablet_outages_are_stored_once_and_shown(admin, client):
    token, _ = pair_device(admin)
    now = datetime.now(timezone.utc)
    outage = {"id": str(uuid.uuid4()), "started_at": (now - timedelta(hours=5)).isoformat(),
              "ended_at": (now - timedelta(hours=2)).isoformat()}
    for _ in range(2):  # resent after a dropped response
        r = client.post("/api/player/heartbeat", json={"outages": [outage]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
    with SessionLocal() as db:
        assert len(db.scalars(select(DeviceOutage)).all()) == 1
    s = admin.get("/api/admin/screens").json()[0]
    assert s["outages_7d"] == 1 and s["outage_minutes_7d"] == 180
    assert s["recent_outages"][0]["minutes"] == 180
    assert s["wifi_unreliable"] is False  # one outage under 4 hours


def test_flaky_wifi_is_flagged(admin, client):
    token, device_id = pair_device(admin)
    now = datetime.now(timezone.utc)
    outages = [{"id": str(uuid.uuid4()), "started_at": (now - timedelta(hours=10 * i + 1)).isoformat(),
                "ended_at": (now - timedelta(hours=10 * i)).isoformat()} for i in range(5)]
    client.post("/api/player/heartbeat", json={"outages": outages}, headers={"Authorization": f"Bearer {token}"})
    assert admin.get("/api/admin/screens").json()[0]["wifi_unreliable"] is True
    # Offline screens are offline on purpose: no suggestion there.
    assert set_mode(admin, device_id, "offline")["wifi_unreliable"] is False


def test_daily_report_lists_visits_and_skips_offline_uptime(admin):
    d = screen(admin, paired_ago=timedelta(days=20), seen_ago=timedelta(days=9))
    set_mode(admin, d, "offline")
    with SessionLocal() as db:
        r = reports.daily_report(db, (NOW - timedelta(days=1)).date(), now=NOW)
    [visit] = r.visits
    assert visit.name == "Lobby" and "New ads to load" in visit.reasons
    assert r.screens[0].uptime_percent is None and r.screens[0].offline_mode
    subject, text, html = reports.render_email(r)
    assert "SCREENS TO VISIT" in text and "offline screen" in text and "Screens to visit" in html
    assert "under 95% uptime" not in subject


def test_replacement_tablet_keeps_connection_mode(admin):
    _, old_id = pair_device(admin, uid="old-tab")
    set_mode(admin, old_id, "offline")
    from fastapi.testclient import TestClient

    from app.main import app
    reg = TestClient(app).post("/api/player/register", json={"device_uid": "new-tab"}).json()
    new = admin.post("/api/admin/screens/pair", json={
        "pairing_code": reg["pairing_code"], "name": "Lobby", "venue_name": "Cafe",
        "replaces_device_id": old_id}).json()
    assert new["connection_mode"] == "offline"
