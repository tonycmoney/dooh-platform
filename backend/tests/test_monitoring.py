"""Alerts (offline, stopped playing), uptime and the daily report."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import alerts, notify, reports
from app.config import settings
from app.db import SessionLocal
from app.models import Alert, AlertKind, Device, DeviceUptime, PlayLog
from tests.conftest import pair_device

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)  # 11:00 am in New York


@pytest.fixture
def outbox(monkeypatch):
    sent: list[tuple[str, str]] = []

    def fake_send(subject, text, html=None):
        sent.append((subject, text))
        return True

    monkeypatch.setattr(notify, "send_email", fake_send)
    return sent


def screen(admin, *, loop_items=(10,), approved=True, paired_ago=timedelta(hours=2), seen_ago=timedelta(0),
           played_ago: timedelta | None = timedelta(seconds=30)):
    """A paired screen with a loop, last heartbeat and last play set as given."""
    media_ids = []
    for seconds in loop_items:
        m = admin.post("/api/admin/text-slides", json={"title": "Promo", "text": "Hi"}).json()
        if not approved:
            admin.post(f"/api/admin/media/{m['id']}/reject")
        media_ids.append((m["id"], seconds))
    loop = admin.post("/api/admin/loops", json={"name": "Main", "items": [
        {"media_id": mid, "duration_seconds": s} for mid, s in media_ids]}).json()
    _, device_id = pair_device(admin, uid=f"android-{uuid.uuid4().hex[:8]}", loop_id=loop["id"])
    with SessionLocal() as db:
        d = db.get(Device, uuid.UUID(device_id))
        d.paired_at = NOW - paired_ago
        d.last_seen_at = NOW - seen_ago
        if played_ago is not None:
            db.add(PlayLog(id=uuid.uuid4(), device_id=d.id, media_title="Promo",
                           started_at=NOW - played_ago, duration_ms=10000, received_at=NOW - played_ago))
        db.commit()
    return uuid.UUID(device_id)


def run(at=NOW, check_offline=True):
    with SessionLocal() as db:
        alerts.evaluate(db, at, check_offline=check_offline)
        alerts.send_notifications(db)
        return db.scalars(select(Alert).order_by(Alert.started_at)).all()


def set_seen(device_id, at):
    with SessionLocal() as db:
        db.get(Device, device_id).last_seen_at = at
        db.commit()


def test_offline_after_10_minutes_one_email_then_recovery(admin, outbox):
    d = screen(admin, seen_ago=timedelta(minutes=9))
    assert run() == [] and outbox == []

    set_seen(d, NOW - timedelta(minutes=11))
    [a] = run()
    assert a.kind == AlertKind.offline and a.resolved_at is None
    assert len(outbox) == 1 and outbox[0][0] == "⚠ Lobby is offline"
    assert "Venue:     Cafe, 1 Main St" in outbox[0][1]

    run(NOW + timedelta(minutes=5))  # still offline: no repeat email
    assert len(outbox) == 1

    set_seen(d, NOW + timedelta(minutes=20))
    [a] = run(NOW + timedelta(minutes=20))
    assert a.resolved_at is not None
    assert outbox[-1][0] == "✓ Lobby is back online" and len(outbox) == 2


def test_blip_that_clears_before_email_sends_nothing(admin, monkeypatch):
    d = screen(admin, seen_ago=timedelta(minutes=11))
    monkeypatch.setattr(notify, "send_email", lambda *a, **k: False)  # email down at first
    run()
    sent = []
    monkeypatch.setattr(notify, "send_email", lambda s, t, h=None: sent.append(s) or True)
    set_seen(d, NOW + timedelta(minutes=1))
    run(NOW + timedelta(minutes=1))
    assert sent == []


def test_no_offline_alerts_during_startup_grace(admin, outbox):
    screen(admin, seen_ago=timedelta(minutes=30))
    assert run(check_offline=False) == [] and outbox == []


def test_not_playing_while_online(admin, outbox):
    d = screen(admin, played_ago=timedelta(minutes=11))
    [a] = run()
    assert a.kind == AlertKind.not_playing and "isn't reporting plays" in a.detail
    assert outbox[0][0] == "⚠ Lobby stopped playing"

    with SessionLocal() as db:
        db.add(PlayLog(id=uuid.uuid4(), device_id=d, media_title="Promo", started_at=NOW,
                       duration_ms=10000, received_at=NOW + timedelta(minutes=1)))
        db.commit()
    [a] = run(NOW + timedelta(minutes=1))
    assert a.resolved_at is not None and outbox[-1][0] == "✓ Lobby is playing again"


def test_long_videos_extend_the_not_playing_limit(admin, outbox):
    screen(admin, loop_items=(600,), played_ago=timedelta(minutes=15))  # limit: 2 x 10 min
    assert run() == []


def test_not_playing_explains_missing_content(admin, outbox):
    screen(admin, approved=False, played_ago=None)
    [a] = run()
    assert "no approved ads" in a.detail


def test_newly_paired_screen_gets_time_to_start(admin, outbox):
    screen(admin, paired_ago=timedelta(minutes=3), played_ago=None)
    assert run() == []


def test_offline_screen_is_not_also_not_playing(admin, outbox):
    screen(admin, seen_ago=timedelta(minutes=30), played_ago=timedelta(minutes=30))
    assert [a.kind for a in run()] == [AlertKind.offline]


def test_heartbeats_mark_five_minute_slots(client, admin):
    token, device_id = pair_device(admin)
    for _ in range(3):
        client.post("/api/player/heartbeat", headers={"Authorization": f"Bearer {token}"}, json={})
    with SessionLocal() as db:
        assert db.query(DeviceUptime).filter_by(device_id=uuid.UUID(device_id)).count() == 1


def test_daily_report_uptime_plays_and_incidents(admin):
    day = date(2026, 10, 4)  # a finished day (the endpoint measures up to the real clock)
    start, end = reports.day_bounds(day)
    assert (end - start) == timedelta(hours=24) and start.hour == 4  # midnight in New York (EDT)
    d = screen(admin, paired_ago=timedelta(days=30), played_ago=None)
    with SessionLocal() as db:
        for i in range(144):  # up for the first 12 hours
            db.add(DeviceUptime(device_id=d, slot_start=start + i * timedelta(minutes=5)))
        db.add(DeviceUptime(device_id=d, slot_start=start - timedelta(minutes=5)))  # previous day
        for title, n in (("Mercato", 30), ("Logo", 12)):
            for i in range(n):
                db.add(PlayLog(id=uuid.uuid4(), device_id=d, media_title=title, duration_ms=10000,
                               started_at=start + timedelta(minutes=i)))
        db.add(PlayLog(id=uuid.uuid4(), device_id=d, media_title="Mercato", duration_ms=10000,
                       started_at=end + timedelta(minutes=1)))  # next day
        db.add(Alert(device_id=d, kind=AlertKind.offline, started_at=start + timedelta(hours=12),
                     resolved_at=start + timedelta(hours=13), detail="x"))
        db.commit()

    r = admin.get("/api/admin/reports/daily", params={"day": "2026-10-04"}).json()
    [s] = r["screens"]
    assert s["uptime_percent"] == 50.0 and s["online_minutes"] == 720
    assert s["plays"] == 42 and [(a["title"], a["plays"]) for a in s["ads"]] == [("Mercato", 30), ("Logo", 12)]
    assert s["incidents"][0]["kind"] == "offline" and s["incidents"][0]["minutes"] == 60
    assert r["total_plays"] == 42 and r["ads"][0] == {"title": "Mercato", "plays": 30, "seconds": 300, "screens": 1}

    with SessionLocal() as db:
        subject, text, html = reports.render_email(reports.daily_report(db, day))
    assert "42 plays" in subject and "1 screen(s) under 95% uptime" in subject
    assert "uptime 50.0%" in text and "Mercato: 30 plays" in text and "Offline 12:00 PM to 1:00 PM" in text
    assert "<table" in html


def test_uptime_only_counts_from_when_tracking_began(admin):
    day = date(2026, 10, 4)
    start, _ = reports.day_bounds(day)
    d = screen(admin, paired_ago=timedelta(days=30), played_ago=None)
    with SessionLocal() as db:
        # Tracking started at noon and the screen was up from then on.
        for i in range(144, 288):
            db.add(DeviceUptime(device_id=d, slot_start=start + i * timedelta(minutes=5)))
        db.commit()
        [s] = reports.daily_report(db, day).screens
        assert s.uptime_percent == 100.0
        [s] = reports.daily_report(db, date(2026, 10, 3)).screens
        assert s.uptime_percent is None  # before tracking: no number rather than 0%


def test_report_goes_out_once_each_morning(admin, outbox):
    with SessionLocal() as db:
        before_7 = datetime(2026, 10, 12, 10, 30, tzinfo=timezone.utc)  # 6:30 am New York
        assert alerts.report_due(db, before_7) is None
        assert alerts.report_due(db, NOW) == date(2026, 10, 11)
        assert alerts.send_daily_report(db, date(2026, 10, 11))
        assert alerts.report_due(db, NOW + timedelta(hours=5)) is None
    assert outbox[0][0].startswith("DOOH daily report, Sun Oct 11, 2026")


def test_email_endpoints(admin, monkeypatch, outbox):
    assert admin.post("/api/admin/alerts/test-email").status_code == 400  # not configured
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_to", "owner@example.com")
    assert admin.post("/api/admin/alerts/test-email").json() == {"sent_to": ["owner@example.com"]}
    assert admin.post("/api/admin/reports/daily/email").status_code == 200
    status = admin.get("/api/admin/monitoring").json()
    assert status["email_configured"] and status["offline_minutes"] == 10


def test_resend_request(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_to", "a@example.com, b@example.com")
    calls = []

    class Res:
        status_code = 200
        text = "{}"

    monkeypatch.setattr(notify.httpx, "post", lambda url, json, timeout, headers: calls.append((url, json, headers)) or Res())
    assert notify.send_email("Hi", "Body")
    url, body, headers = calls[0]
    assert url == "https://api.resend.com/emails" and headers["Authorization"] == "Bearer re_test"
    assert body["to"] == ["a@example.com", "b@example.com"] and body["subject"] == "Hi"
