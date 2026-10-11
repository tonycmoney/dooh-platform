"""Daily report: each screen's uptime and incidents, and how many times each
ad played, for one local calendar day."""

from datetime import date, datetime, time, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import notify, schemas
from .config import settings
from .models import Alert, AlertKind, Device, DeviceUptime, PlayLog
from .services import UPTIME_SLOT

KIND_LABELS = {AlertKind.offline: "Offline", AlertKind.not_playing: "Not playing"}


def day_bounds(day: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.timezone)
    start = datetime.combine(day, time(), tz)
    end = datetime.combine(day + timedelta(days=1), time(), tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _fmt_local(at: datetime) -> str:
    return at.astimezone(ZoneInfo(settings.timezone)).strftime("%-I:%M %p")


def daily_report(db: Session, day: date, now: datetime | None = None) -> schemas.DailyReport:
    now = now or datetime.now(timezone.utc)
    start, end = day_bounds(day)
    devices = db.scalars(select(Device).where(Device.paired_at.is_not(None)).order_by(Device.name)).all()

    screens = []
    for d in devices:
        # Measure from when the screen was paired (if that day) up to now (if today).
        window_start = max(start, d.paired_at) if d.paired_at else start
        window_end = min(end, now)
        expected = max(0, int((window_end - window_start) / UPTIME_SLOT))
        slots = db.scalar(
            select(func.count()).select_from(DeviceUptime)
            .where(DeviceUptime.device_id == d.id, DeviceUptime.slot_start > window_start - UPTIME_SLOT,
                   DeviceUptime.slot_start < window_end)
        ) or 0
        uptime = None if expected == 0 else min(100.0, 100.0 * slots / expected)

        plays = db.execute(
            select(PlayLog.media_title, func.count(), func.sum(PlayLog.duration_ms))
            .where(PlayLog.device_id == d.id, PlayLog.started_at >= start, PlayLog.started_at < end)
            .group_by(PlayLog.media_title).order_by(func.count().desc())
        ).all()
        incidents = db.scalars(
            select(Alert).where(Alert.device_id == d.id, Alert.started_at < end,
                                (Alert.resolved_at.is_(None)) | (Alert.resolved_at >= start))
            .order_by(Alert.started_at)
        ).all()
        screens.append(schemas.ScreenReport(
            device_id=d.id,
            name=d.name or "Unnamed screen",
            venue_name=d.venue_name,
            uptime_percent=None if uptime is None else round(uptime, 1),
            online_minutes=slots * 5,
            plays=sum(p[1] for p in plays),
            ads=[schemas.AdPlays(title=p[0] or "(untitled)", plays=p[1], seconds=round((p[2] or 0) / 1000))
                 for p in plays],
            incidents=[schemas.IncidentOut(
                kind=a.kind, detail=a.detail, started_at=a.started_at, resolved_at=a.resolved_at,
                minutes=round(((a.resolved_at or min(end, now)) - max(a.started_at, start)).total_seconds() / 60),
            ) for a in incidents],
        ))

    totals: dict[str, schemas.AdPlays] = {}
    for s in screens:
        for ad in s.ads:
            t = totals.setdefault(ad.title, schemas.AdPlays(title=ad.title, plays=0, seconds=0, screens=0))
            t.plays += ad.plays
            t.seconds += ad.seconds
            t.screens = (t.screens or 0) + 1
    return schemas.DailyReport(
        day=day,
        timezone=settings.timezone,
        screens=screens,
        ads=sorted(totals.values(), key=lambda a: a.plays, reverse=True),
        total_plays=sum(s.plays for s in screens),
    )


# --- Email --------------------------------------------------------------------


def _uptime_text(s: schemas.ScreenReport) -> str:
    return "n/a" if s.uptime_percent is None else f"{s.uptime_percent:.1f}%"


def render_email(r: schemas.DailyReport) -> tuple[str, str, str]:
    """(subject, plain text, HTML)."""
    label = r.day.strftime("%a %b %-d, %Y")
    low = [s for s in r.screens if s.uptime_percent is not None and s.uptime_percent < 95]
    subject = f"DOOH daily report, {label}: {r.total_plays} plays" + (f", {len(low)} screen(s) under 95% uptime" if low else "")

    text = [f"Daily report for {label} ({r.timezone})", "", "SCREENS"]
    for s in r.screens:
        text.append(f"- {s.name} ({s.venue_name or '-'}): uptime {_uptime_text(s)}, {s.plays} plays")
        for i in s.incidents:
            end = _fmt_local(i.resolved_at) if i.resolved_at else "still open"
            text.append(f"    {KIND_LABELS[i.kind]} {_fmt_local(i.started_at)} to {end} ({i.minutes} min)")
    text += ["", "PLAYS PER AD (all screens)"]
    text += [f"- {a.title}: {a.plays} plays, {a.seconds // 60} min on screen" for a in r.ads] or ["- none"]
    if link := notify.dashboard_link("/reports"):
        text += ["", f"Full report: {link}"]

    cell = 'style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:left"'
    def row(*cols: str, head: bool = False) -> str:
        tag = "th" if head else "td"
        return "<tr>" + "".join(f"<{tag} {cell}>{c}</{tag}>" for c in cols) + "</tr>"
    def table(rows: list[str]) -> str:
        return f'<table style="border-collapse:collapse;font:14px system-ui,sans-serif;margin:8px 0 20px">{"".join(rows)}</table>'

    screen_rows = [row("Screen", "Venue", "Uptime", "Plays", "Incidents", head=True)]
    for s in r.screens:
        incidents = "<br>".join(
            f"{KIND_LABELS[i.kind]} {_fmt_local(i.started_at)}–{_fmt_local(i.resolved_at) if i.resolved_at else 'open'} ({i.minutes} min)"
            for i in s.incidents) or "none"
        color = "#b91c1c" if s.uptime_percent is not None and s.uptime_percent < 95 else "#15803d"
        screen_rows.append(row(escape(s.name), escape(s.venue_name or "-"),
                               f'<b style="color:{color}">{_uptime_text(s)}</b>', str(s.plays), incidents))
    ad_rows = [row("Ad", "Plays", "Time on screen", "Screens", head=True)]
    ad_rows += [row(escape(a.title), str(a.plays), f"{a.seconds // 60} min", str(a.screens or 1)) for a in r.ads]
    html = (f'<div style="font:14px system-ui,sans-serif;color:#111"><h2 style="margin:0 0 4px">Daily report</h2>'
            f'<div style="color:#666">{label} · {r.timezone} · {r.total_plays} plays</div>'
            f'<h3>Screens</h3>{table(screen_rows)}<h3>Plays per ad</h3>{table(ad_rows)}')
    if link := notify.dashboard_link("/reports"):
        html += f'<p><a href="{escape(link)}">Open the full report</a></p>'
    html += "</div>"
    return subject, "\n".join(text), html
