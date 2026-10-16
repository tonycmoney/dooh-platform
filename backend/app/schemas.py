import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from datetime import date

from .models import AlertKind, ApprovalStatus, FileStatus, FitMode, MediaKind, VideoFit

HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Player -------------------------------------------------------------------


class RegisterIn(BaseModel):
    device_uid: Annotated[str, StringConstraints(min_length=4, max_length=128)]
    app_version: str | None = None


class RegisterOut(BaseModel):
    pairing_code: str
    claim_secret: str


class PairingStatusIn(BaseModel):
    device_uid: str
    claim_secret: str


class PairingStatusOut(BaseModel):
    paired: bool
    token: str | None = None
    device_id: uuid.UUID | None = None
    name: str | None = None
    venue_name: str | None = None


class HeartbeatIn(BaseModel):
    app_version: str | None = None
    battery_level: Annotated[int, Field(ge=0, le=100)] | None = None
    is_charging: bool | None = None
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None
    location_accuracy_m: float | None = None
    now_playing_media_id: uuid.UUID | None = None
    now_playing_title: str | None = None
    manifest_version: str | None = None


class MaintenancePin(BaseModel):
    """PBKDF2-HMAC-SHA256 of the PIN; tablets verify PINs against it offline."""

    salt: str  # base64
    hash: str  # hex
    iterations: int


class HeartbeatOut(BaseModel):
    manifest_version: str
    name: str | None
    venue_name: str | None
    maintenance_pin: MaintenancePin | None = None


class TextSlideProps(BaseModel):
    text: str
    font_size: int
    text_color: str
    background_color: str


class ManifestItem(BaseModel):
    item_id: uuid.UUID
    media_id: uuid.UUID
    kind: MediaKind
    title: str
    duration_seconds: int
    video_fit: VideoFit
    url: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    media_duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    # Already 1080x1920 with its own white border: letterbox it in white,
    # not over a blur, on screens of a different shape.
    framed: bool = False
    text: TextSlideProps | None = None


class Manifest(BaseModel):
    version: str
    loop_id: uuid.UUID | None
    loop_name: str | None
    items: list[ManifestItem]


class PlayIn(BaseModel):
    id: uuid.UUID
    media_id: uuid.UUID | None = None
    media_title: str | None = None
    loop_id: uuid.UUID | None = None
    started_at: datetime
    duration_ms: Annotated[int, Field(ge=0)]


class PlaysIn(BaseModel):
    plays: Annotated[list[PlayIn], Field(max_length=500)]


class PlaysOut(BaseModel):
    accepted: list[uuid.UUID]
    inserted: int


# --- Admin --------------------------------------------------------------------


class LoginIn(BaseModel):
    password: str


class LoginOut(BaseModel):
    token: str


class BackupOut(BaseModel):
    name: str
    size_bytes: int
    created_at: datetime


class BackupsOut(BaseModel):
    daily_enabled: bool
    keep_days: int
    backups: list[BackupOut]


class SettingsOut(BaseModel):
    auto_approve: bool
    maintenance_pin_set: bool = False


class MaintenancePinIn(BaseModel):
    pin: Annotated[str, StringConstraints(pattern=r"^[0-9]{4,8}$")]


class SettingsIn(BaseModel):
    auto_approve: bool


class MediaOut(ORM):
    id: uuid.UUID
    kind: MediaKind
    title: str
    status: ApprovalStatus
    url: str | None = None
    thumbnail_url: str | None = None
    original_name: str | None
    mime_type: str | None
    size_bytes: int | None
    width: int | None
    height: int | None
    duration_seconds: float | None
    text: str | None
    font_size: int | None
    text_color: str | None
    background_color: str | None
    fit_mode: FitMode
    source_width: int | None = None
    source_height: int | None = None
    format_note: str | None = None  # e.g. "Landscape 1600×900: shown whole over a blurred background"
    created_at: datetime
    used_in_loops: int = 0


class MediaUpdate(BaseModel):
    title: ShortText | None = None
    fit_mode: FitMode | None = None


class TextSlideIn(BaseModel):
    title: ShortText
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    font_size: Annotated[int, Field(ge=8, le=400)] = 96  # unused: text is auto-sized
    text_color: HexColor = "#FFFFFF"
    background_color: HexColor = "#000000"


class LoopItemIn(BaseModel):
    media_id: uuid.UUID
    duration_seconds: Annotated[int, Field(ge=1, le=3600)] = 10
    video_fit: VideoFit = VideoFit.loop


class LoopIn(BaseModel):
    name: ShortText
    items: list[LoopItemIn] = []


class LoopItemOut(ORM):
    id: uuid.UUID
    media_id: uuid.UUID
    position: int
    duration_seconds: int
    video_fit: VideoFit
    media: MediaOut


class LoopOut(ORM):
    id: uuid.UUID
    name: str
    items: list[LoopItemOut]
    device_ids: list[uuid.UUID]
    total_seconds: int
    updated_at: datetime


class LoopSummary(ORM):
    id: uuid.UUID
    name: str
    item_count: int
    total_seconds: int
    device_count: int
    updated_at: datetime


class AssignIn(BaseModel):
    device_ids: list[uuid.UUID]


class PairIn(BaseModel):
    pairing_code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=6, max_length=6)]
    name: ShortText
    venue_name: ShortText
    venue_address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    loop_id: uuid.UUID | None = None
    # Swapping in a new tablet: it takes over this screen's name, venue, loop
    # and play history, and the old tablet's pairing is removed.
    replaces_device_id: uuid.UUID | None = None


class DeviceUpdate(BaseModel):
    name: ShortText | None = None
    venue_name: ShortText | None = None
    venue_address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    loop_id: uuid.UUID | None = None
    clear_loop: bool = False


class DeviceOut(ORM):
    id: uuid.UUID
    device_uid: str
    name: str | None
    venue_name: str | None
    venue_address: str | None
    latitude: float | None
    longitude: float | None
    location_accuracy_m: float | None
    location_at: datetime | None
    online: bool
    last_seen_at: datetime | None
    battery_level: int | None
    is_charging: bool | None
    app_version: str | None
    now_playing_title: str | None
    now_playing_media_id: uuid.UUID | None
    loop_id: uuid.UUID | None
    loop_name: str | None
    in_sync: bool
    paired_at: datetime | None


class PlayLogOut(ORM):
    id: uuid.UUID
    device_id: uuid.UUID
    media_id: uuid.UUID | None
    media_title: str | None
    loop_id: uuid.UUID | None
    started_at: datetime
    duration_ms: int
    received_at: datetime


# --- Customer website ---------------------------------------------------------

Line = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


class WebsiteOrderIn(BaseModel):
    """An ad order from the customer website (see docs/website-orders.md)."""

    order_id: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_.-]{1,80}$")]
    business_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    contact_name: Line | None = None
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    plan: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    plan_name: Line | None = None
    city: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    ad_choice: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    ad_text: LongText | None = None
    notes: LongText | None = None
    file_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None
    file_name: Line | None = None


class WebsiteOrderAccepted(BaseModel):
    order_id: str
    received: bool = True
    duplicate: bool = False
    file: FileStatus


class OrderOut(BaseModel):
    id: uuid.UUID
    external_id: str
    business_name: str
    contact_name: str | None
    email: str
    phone: str | None
    plan: str
    plan_name: str | None
    city: str | None
    ad_choice: str | None
    ad_text: str | None
    notes: str | None
    file_name: str | None
    file_status: FileStatus
    file_error: str | None
    can_retry: bool
    media: MediaOut | None
    created_at: datetime
    # From Stripe: paid | pending | failed | abandoned | awaiting (no word yet)
    payment_status: str = "awaiting"
    paid_amount: int | None = None  # smallest currency unit (cents)
    paid_currency: str | None = None
    paid_at: datetime | None = None


# --- Alerts and reports -------------------------------------------------------


class AdPlays(BaseModel):
    title: str
    plays: int
    seconds: int
    screens: int | None = None


class IncidentOut(BaseModel):
    kind: AlertKind
    detail: str | None
    started_at: datetime
    resolved_at: datetime | None
    minutes: int


class ScreenReport(BaseModel):
    device_id: uuid.UUID
    name: str
    venue_name: str | None
    uptime_percent: float | None  # None: the screen didn't exist yet that day
    online_minutes: int
    plays: int
    ads: list[AdPlays]
    incidents: list[IncidentOut]


class DailyReport(BaseModel):
    day: date
    timezone: str
    screens: list[ScreenReport]
    ads: list[AdPlays]
    total_plays: int


class AlertOut(BaseModel):
    id: uuid.UUID
    screen: str
    kind: AlertKind
    detail: str | None
    started_at: datetime
    resolved_at: datetime | None
    emailed: bool


class MonitoringStatus(BaseModel):
    monitoring: bool
    email_configured: bool
    alert_email_to: list[str]
    offline_minutes: int
    not_playing_minutes: int
    report_hour: int
    timezone: str


# --- Hosts (businesses that host screens) -------------------------------------

Percent = Annotated[int, Field(ge=0, le=100)]


class HostIn(BaseModel):
    name: ShortText
    business_name: ShortText
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    share_percent: Percent | None = None


class HostUpdate(BaseModel):
    name: ShortText | None = None
    business_name: ShortText | None = None
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    share_percent: Percent | None = None


class HostScreensIn(BaseModel):
    device_ids: list[uuid.UUID]


class PayoutIn(BaseModel):
    month: date  # any day in the month


class PayoutOut(ORM):
    month: date
    amount: int
    currency: str
    stripe_transfer_id: str | None
    created_at: datetime


class HostScreenMonthOut(BaseModel):
    device_id: uuid.UUID
    name: str
    venue_name: str | None
    online: bool
    last_seen_at: datetime | None
    uptime_percent: float | None
    plays: int
    seconds: int
    revenue: int
    earnings: int


class HostMonthOut(BaseModel):
    month: date
    share_percent: int
    revenue: int
    earnings: int
    screens: list[HostScreenMonthOut]
    payout: PayoutOut | None


class HostOut(BaseModel):
    id: uuid.UUID
    name: str
    business_name: str
    email: str | None
    phone: str | None
    share_percent: int
    link: str
    payout_status: str  # not_started | pending | ready
    device_ids: list[uuid.UUID]
    this_month: HostMonthOut
    last_month: HostMonthOut
    created_at: datetime


class HostPortalOut(BaseModel):
    business_name: str
    name: str
    share_percent: int
    timezone: str
    payout_status: str
    payouts_available: bool
    month: HostMonthOut
    history: list[HostMonthOut]
    payouts: list[PayoutOut]


class OnboardingLinkOut(BaseModel):
    url: str
