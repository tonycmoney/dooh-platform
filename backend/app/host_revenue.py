"""What each host's screens earned.

For a calendar month (local time): every advertiser subscription payment
collected that month (AdPayment, recurring lines only) is split across the
screens that played that advertiser's ad, in proportion to seconds on screen
that month. A host earns its share_percent of what its screens brought in.
Revenue for an ad that played nowhere that month isn't assigned to any host.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import AdPayment, Device, DeviceUptime, Host, HostPayout, PlayLog, StripePayment, WebsiteOrder
from .services import UPTIME_SLOT, is_online


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(month: date) -> date:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1)


def month_bounds(month: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.timezone)
    start = datetime.combine(month_start(month), time(), tz)
    end = datetime.combine(next_month(month_start(month)), time(), tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def current_month(now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ZoneInfo(settings.timezone)).date().replace(day=1)


def revenue_by_media(db: Session, start: datetime, end: datetime) -> dict:
    """Cents collected in [start, end) per ad (media id)."""
    rows = db.execute(
        select(WebsiteOrder.media_id, AdPayment.invoice_id, AdPayment.amount)
        .join(StripePayment, StripePayment.subscription_id == AdPayment.subscription_id)
        .join(WebsiteOrder, WebsiteOrder.external_id == StripePayment.client_reference_id)
        .where(AdPayment.paid_at >= start, AdPayment.paid_at < end, WebsiteOrder.media_id.is_not(None))
    ).all()
    seen: set[str] = set()  # one invoice can match more than one checkout row
    totals: dict = defaultdict(int)
    for media_id, invoice_id, amount in rows:
        if invoice_id not in seen:
            seen.add(invoice_id)
            totals[media_id] += amount
    return totals


def revenue_by_device(db: Session, start: datetime, end: datetime) -> dict:
    """Cents (float, rounded by the caller) each screen brought in."""
    revenue = revenue_by_media(db, start, end)
    if not revenue:
        return {}
    plays = db.execute(
        select(PlayLog.media_id, PlayLog.device_id, func.sum(PlayLog.duration_ms))
        .where(PlayLog.started_at >= start, PlayLog.started_at < end, PlayLog.media_id.in_(list(revenue)))
        .group_by(PlayLog.media_id, PlayLog.device_id)
    ).all()
    by_media: dict = defaultdict(dict)
    for media_id, device_id, ms in plays:
        by_media[media_id][device_id] = ms or 0
    result: dict = defaultdict(float)
    for media_id, cents in revenue.items():
        total = sum(by_media[media_id].values())
        if total <= 0:
            continue
        for device_id, ms in by_media[media_id].items():
            result[device_id] += cents * ms / total
    return result


def uptime_percent(db: Session, device: Device, start: datetime, end: datetime, now: datetime) -> float | None:
    first_slot = db.scalar(select(func.min(DeviceUptime.slot_start)).where(DeviceUptime.device_id == device.id))
    if first_slot is None:
        return None
    window_start = max(t for t in (start, device.paired_at, first_slot) if t is not None)
    window_end = min(end, now)
    expected = max(0, int((window_end - window_start) / UPTIME_SLOT))
    if expected == 0:
        return None
    slots = db.scalar(
        select(func.count()).select_from(DeviceUptime)
        .where(DeviceUptime.device_id == device.id, DeviceUptime.slot_start > window_start - UPTIME_SLOT,
               DeviceUptime.slot_start < window_end)
    ) or 0
    return round(min(100.0, 100.0 * slots / expected), 1)


@dataclass
class ScreenMonth:
    device_id: object
    name: str
    venue_name: str | None
    online: bool
    last_seen_at: datetime | None
    uptime_percent: float | None
    plays: int
    seconds: int
    revenue: int  # cents the screen brought in
    earnings: int  # the host's share, cents


@dataclass
class HostMonth:
    month: date
    share_percent: int
    revenue: int
    earnings: int
    screens: list[ScreenMonth] = field(default_factory=list)
    payout: HostPayout | None = None


def host_month(db: Session, host: Host, month: date, now: datetime | None = None,
               device_revenue: dict | None = None) -> HostMonth:
    now = now or datetime.now(timezone.utc)
    month = month_start(month)
    start, end = month_bounds(month)
    if device_revenue is None:
        device_revenue = revenue_by_device(db, start, end)
    devices = db.scalars(select(Device).where(Device.host_id == host.id).order_by(Device.name)).all()
    screens = []
    for d in devices:
        plays, ms = db.execute(
            select(func.count(), func.coalesce(func.sum(PlayLog.duration_ms), 0))
            .where(PlayLog.device_id == d.id, PlayLog.started_at >= start, PlayLog.started_at < end)
        ).one()
        revenue = device_revenue.get(d.id, 0.0)
        screens.append(ScreenMonth(
            device_id=d.id, name=d.name or "Screen", venue_name=d.venue_name, online=is_online(d, now),
            last_seen_at=d.last_seen_at, uptime_percent=uptime_percent(db, d, start, end, now),
            plays=plays, seconds=round(ms / 1000), revenue=round(revenue),
            earnings=round(revenue * host.share_percent / 100),
        ))
    total = sum(device_revenue.get(d.id, 0.0) for d in devices)
    payout = db.scalar(select(HostPayout).where(HostPayout.host_id == host.id, HostPayout.month == month))
    return HostMonth(month=month, share_percent=host.share_percent, revenue=round(total),
                     earnings=round(total * host.share_percent / 100), screens=screens, payout=payout)


def recent_months(month: date, count: int) -> list[date]:
    months = [month_start(month)]
    while len(months) < count:
        months.append((months[-1] - timedelta(days=1)).replace(day=1))
    return months
