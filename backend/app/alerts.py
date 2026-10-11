"""Screen alerts and the daily report schedule.

Every minute the monitor checks each paired screen:
- offline: no heartbeat for ALERT_OFFLINE_MINUTES
- not playing: online, but no play has reached the server for
  ALERT_NOT_PLAYING_MINUTES (or twice its loop's longest item, if longer)

Each incident is one Alert row: one email when it starts, one when it clears.
A problem that clears before its email is sent (a blip) sends nothing.
"""

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import notify, reports
from .config import settings
from .db import SessionLocal
from .models import Alert, AlertKind, ApprovalStatus, Device, LoopItem, Media, PlayLog, Setting

log = logging.getLogger("dooh.alerts")

CHECK_EVERY_SECONDS = 60
# After a restart, give screens time to check in again before calling them
# offline (a deploy shouldn't page you).
STARTUP_GRACE_SECONDS = 3 * 60


def local(at: datetime | None) -> str:
    if at is None:
        return "never"
    return at.astimezone(ZoneInfo(settings.timezone)).strftime("%a %b %-d, %-I:%M %p")


def _open_alert(db: Session, device: Device, kind: AlertKind) -> Alert | None:
    return db.scalar(
        select(Alert).where(Alert.device_id == device.id, Alert.kind == kind, Alert.resolved_at.is_(None))
    )


def _not_playing_threshold(db: Session, device: Device) -> timedelta:
    longest = 0
    if device.loop_id:
        longest = db.scalar(select(func.max(LoopItem.duration_seconds)).where(LoopItem.loop_id == device.loop_id)) or 0
    return max(timedelta(minutes=settings.alert_not_playing_minutes), timedelta(seconds=2 * longest))


def _not_playing_reason(db: Session, device: Device) -> str:
    if device.loop_id is None:
        return "No loop is assigned to this screen."
    approved = db.scalar(
        select(func.count()).select_from(LoopItem).join(Media, LoopItem.media_id == Media.id)
        .where(LoopItem.loop_id == device.loop_id, Media.status == ApprovalStatus.approved)
    )
    if not approved:
        return "Its loop has no approved ads, so there's nothing to play."
    return "The tablet is online but isn't reporting plays; the player may be stuck."


def _is_not_playing(db: Session, device: Device, now: datetime) -> bool:
    threshold = _not_playing_threshold(db, device)
    # Online long enough to have played something since pairing or since it
    # came back from being offline.
    recovered = db.scalar(
        select(func.max(Alert.resolved_at)).where(Alert.device_id == device.id, Alert.kind == AlertKind.offline)
    )
    for since in (device.paired_at, recovered):
        if since and now - since < threshold:
            return False
    last_play = db.scalar(select(func.max(PlayLog.received_at)).where(PlayLog.device_id == device.id))
    return last_play is None or now - last_play > threshold


def evaluate(db: Session, now: datetime | None = None, *, check_offline: bool = True) -> None:
    """Opens and resolves alerts for every paired screen."""
    now = now or datetime.now(timezone.utc)
    offline_after = timedelta(minutes=settings.alert_offline_minutes)
    devices = db.scalars(select(Device).where(Device.paired_at.is_not(None))).all()
    for device in devices:
        seen = device.last_seen_at or device.paired_at
        offline = seen is not None and now - seen > offline_after
        current = _open_alert(db, device, AlertKind.offline)
        if offline and check_offline and current is None:
            db.add(Alert(device_id=device.id, kind=AlertKind.offline, started_at=seen,
                         detail=f"No check-in since {local(device.last_seen_at)}."))
        elif not offline and current is not None:
            current.resolved_at = now
        db.flush()  # the not-playing check below must see a just-closed offline alert

        stalled = not offline and _is_not_playing(db, device, now)
        current = _open_alert(db, device, AlertKind.not_playing)
        if stalled and current is None:
            db.add(Alert(device_id=device.id, kind=AlertKind.not_playing, started_at=now,
                         detail=_not_playing_reason(db, device)))
        elif not stalled and current is not None:
            current.resolved_at = now  # playing again, or offline (that alert takes over)
        db.flush()
    db.commit()


# --- Emails -------------------------------------------------------------------

TITLES = {AlertKind.offline: "is offline", AlertKind.not_playing: "stopped playing"}


def _screen_lines(device: Device) -> list[str]:
    battery = "unknown" if device.battery_level is None else (
        f"{device.battery_level}%" + (" (charging)" if device.is_charging else " (NOT charging)"))
    return [
        f"Screen:    {device.name}",
        f"Venue:     {device.venue_name or '-'}" + (f", {device.venue_address}" if device.venue_address else ""),
        f"Last seen: {local(device.last_seen_at)}",
        f"Battery:   {battery}",
        f"Playing:   {device.now_playing_title or '-'}",
        f"Loop:      {device.loop.name if device.loop else 'none'}",
    ]


def alert_email(alert: Alert, device: Device) -> tuple[str, str]:
    lines = [f"{device.name} {TITLES[alert.kind]} (since {local(alert.started_at)}).", "",
             alert.detail or "", "", *_screen_lines(device)]
    if alert.kind is AlertKind.offline:
        lines += ["", "Common causes: the venue's WiFi or power is off, or the tablet was unplugged."]
    if link := notify.dashboard_link("/screens"):
        lines += ["", f"Dashboard: {link}"]
    return f"⚠ {device.name} {TITLES[alert.kind]}", "\n".join(lines)


def recovery_email(alert: Alert, device: Device) -> tuple[str, str]:
    minutes = round((alert.resolved_at - alert.started_at).total_seconds() / 60)
    what = "back online" if alert.kind is AlertKind.offline else "playing again"
    lines = [f"{device.name} is {what} after about {minutes} min (since {local(alert.started_at)}).", "",
             *_screen_lines(device)]
    return f"✓ {device.name} is {what}", "\n".join(lines)


def send_notifications(db: Session) -> None:
    pending = db.scalars(
        select(Alert).options(selectinload(Alert.device).selectinload(Device.loop))
        .where((Alert.notified_at.is_(None)) | (Alert.resolved_at.is_not(None) & Alert.resolved_notified_at.is_(None)))
        .order_by(Alert.started_at)
    ).all()
    now = datetime.now(timezone.utc)
    for alert in pending:
        device = alert.device
        if alert.notified_at is None and alert.resolved_at is not None:
            alert.notified_at = alert.resolved_notified_at = now  # cleared before we told anyone
        elif alert.notified_at is None:
            if notify.send_email(*alert_email(alert, device)):
                alert.notified_at = now
        elif notify.send_email(*recovery_email(alert, device)):
            alert.resolved_notified_at = now
        db.commit()


# --- Daily report -------------------------------------------------------------

LAST_REPORT_KEY = "last_daily_report"


def report_due(db: Session, now: datetime) -> date | None:
    """The day to report on, if this morning's report hasn't gone out yet."""
    local_now = now.astimezone(ZoneInfo(settings.timezone))
    if local_now.hour < settings.daily_report_hour:
        return None
    day = local_now.date() - timedelta(days=1)
    row = db.get(Setting, LAST_REPORT_KEY)
    return None if row and row.value >= day.isoformat() else day


def send_daily_report(db: Session, day: date) -> bool:
    report = reports.daily_report(db, day)
    sent = notify.send_email(*reports.render_email(report))
    if sent:
        row = db.get(Setting, LAST_REPORT_KEY) or Setting(key=LAST_REPORT_KEY, value="")
        row.value = day.isoformat()
        db.add(row)
        db.commit()
    return sent


# --- Monitor thread -----------------------------------------------------------


def _loop(stop: threading.Event) -> None:
    started = datetime.now(timezone.utc)
    while not stop.wait(CHECK_EVERY_SECONDS):
        now = datetime.now(timezone.utc)
        try:
            with SessionLocal() as db:
                evaluate(db, now, check_offline=(now - started).total_seconds() > STARTUP_GRACE_SECONDS)
                send_notifications(db)
                if notify.email_configured() and (day := report_due(db, now)):
                    send_daily_report(db, day)
        except Exception:
            log.exception("Monitor check failed")


def start_monitor() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), name="screen-monitor", daemon=True).start()
    return stop

