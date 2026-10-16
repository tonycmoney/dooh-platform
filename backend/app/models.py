import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MediaKind(str, enum.Enum):
    image = "image"
    video = "video"
    text = "text"


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class FitMode(str, enum.Enum):
    fit = "fit"  # show everything; other shapes go over a blurred background
    fill = "fill"  # cover the screen, cropping the edges


class VideoFit(str, enum.Enum):
    loop = "loop"  # repeat the video until the item's time is up
    cut = "cut"  # play once; stop early if the item's time is shorter


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Permanent hardware-level ID reported by the tablet (Android ANDROID_ID).
    device_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    # Pairing: the tablet shows pairing_code; claim_secret proves it is the same
    # tablet when it collects its token, so knowing the code alone is not enough.
    pairing_code: Mapped[str | None] = mapped_column(String(8), unique=True)
    claim_secret_hash: Mapped[str | None] = mapped_column(String(64))
    pending_token: Mapped[str | None] = mapped_column(String(128))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    name: Mapped[str | None] = mapped_column(String(200))
    venue_name: Mapped[str | None] = mapped_column(String(200))
    venue_address: Mapped[str | None] = mapped_column(Text)

    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    location_accuracy_m: Mapped[float | None] = mapped_column(Float)
    location_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    battery_level: Mapped[int | None] = mapped_column(Integer)
    is_charging: Mapped[bool | None]
    app_version: Mapped[str | None] = mapped_column(String(50))
    now_playing_media_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    now_playing_title: Mapped[str | None] = mapped_column(String(300))
    manifest_version: Mapped[str | None] = mapped_column(String(64))

    loop_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("loops.id", ondelete="SET NULL")
    )
    loop: Mapped["Loop | None"] = relationship(back_populates="devices")
    host_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hosts.id", ondelete="SET NULL"), index=True
    )
    host: Mapped["Host | None"] = relationship(back_populates="devices")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Media(Base):
    __tablename__ = "media"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[MediaKind] = mapped_column(Enum(MediaKind, name="media_kind"))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"), default=ApprovalStatus.pending
    )

    # The formatted file screens play: 1080x1920 with a white border (images,
    # videos and rendered text slides). width/height describe this file.
    filename: Mapped[str | None] = mapped_column(String(300))
    original_name: Mapped[str | None] = mapped_column(String(300))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    thumbnail_filename: Mapped[str | None] = mapped_column(String(300))

    # The original upload, kept privately so the item can be reformatted.
    source_filename: Mapped[str | None] = mapped_column(String(300))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    source_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    source_width: Mapped[int | None] = mapped_column(Integer)
    source_height: Mapped[int | None] = mapped_column(Integer)
    fit_mode: Mapped[FitMode] = mapped_column(
        Enum(FitMode, name="fit_mode"), default=FitMode.fit, server_default=FitMode.fit.value
    )
    format_version: Mapped[int | None] = mapped_column(Integer)

    # Text slides
    text: Mapped[str | None] = mapped_column(Text)
    font_size: Mapped[int | None] = mapped_column(Integer)
    text_color: Mapped[str | None] = mapped_column(String(9))
    background_color: Mapped[str | None] = mapped_column(String(9))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Loop(Base):
    __tablename__ = "loops"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    items: Mapped[list["LoopItem"]] = relationship(
        back_populates="loop",
        order_by="LoopItem.position",
        cascade="all, delete-orphan",
    )
    devices: Mapped[list[Device]] = relationship(back_populates="loop")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LoopItem(Base):
    __tablename__ = "loop_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    loop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("loops.id", ondelete="CASCADE"), index=True
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=10)
    video_fit: Mapped[VideoFit] = mapped_column(
        Enum(VideoFit, name="video_fit"), default=VideoFit.loop
    )

    loop: Mapped[Loop] = relationship(back_populates="items")
    media: Mapped[Media] = relationship()


class PlayLog(Base):
    """Proof of play. The primary key is generated on the tablet, so resending
    the same play is a no-op."""

    __tablename__ = "play_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    # Not foreign keys: logs must survive media/loop deletion.
    media_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    media_title: Mapped[str | None] = mapped_column(String(300))
    loop_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeviceUptime(Base):
    """One row per screen per 5-minute slot in which it checked in. Uptime for
    a day is the share of its 288 slots that have a row."""

    __tablename__ = "device_uptime"

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)


class AlertKind(str, enum.Enum):
    offline = "offline"  # no heartbeat for a while
    not_playing = "not_playing"  # online, but no plays coming in


class Alert(Base):
    """An incident on a screen, from detection until it clears. Emails go out
    when it starts and when it clears."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    device: Mapped["Device"] = relationship()
    kind: Mapped[AlertKind] = mapped_column(Enum(AlertKind, name="alert_kind"))
    detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FileStatus(str, enum.Enum):
    none = "none"  # the customer chose "Design it for me", or no file was sent
    queued = "queued"  # waiting to be downloaded and formatted
    ready = "ready"  # formatted; see media_id
    failed = "failed"  # see file_error


class WebsiteOrder(Base):
    """An ad order from the customer website. Its file becomes a media item
    that always waits in the approval queue."""

    __tablename__ = "website_orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(80), unique=True)  # the website's order ID
    business_name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    plan: Mapped[str] = mapped_column(String(80))
    plan_name: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(120))
    ad_choice: Mapped[str | None] = mapped_column(String(80))
    ad_text: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    file_name: Mapped[str | None] = mapped_column(String(300))
    # Signed download link; cleared once the file is stored.
    file_url: Mapped[str | None] = mapped_column(Text)
    file_status: Mapped[FileStatus] = mapped_column(
        Enum(FileStatus, name="order_file_status"), default=FileStatus.none
    )
    file_error: Mapped[str | None] = mapped_column(Text)
    media_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    media: Mapped["Media | None"] = relationship()

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PaymentStatus(str, enum.Enum):
    paid = "paid"
    pending = "pending"  # completed, but a bank payment is still clearing
    failed = "failed"
    expired = "expired"  # checkout abandoned (Stripe expires it after 24 h)


# When Stripe sends events for one checkout out of order, keep the strongest.
PAYMENT_PRECEDENCE = {PaymentStatus.expired: 1, PaymentStatus.pending: 2, PaymentStatus.failed: 3, PaymentStatus.paid: 4}


class StripePayment(Base):
    """One Stripe Checkout session, matched to a website order by the order
    ID the website passes as client_reference_id."""

    __tablename__ = "stripe_payments"

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    client_reference_id: Mapped[str | None] = mapped_column(String(200), index=True)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, name="payment_status"))
    amount_total: Mapped[int | None] = mapped_column(Integer)  # smallest currency unit (cents)
    currency: Mapped[str | None] = mapped_column(String(10))
    customer_email: Mapped[str | None] = mapped_column(String(255))
    livemode: Mapped[bool] = mapped_column(default=True)
    # Set when the checkout started a subscription; links its monthly
    # invoices (AdPayment) back to the order.
    subscription_id: Mapped[str | None] = mapped_column(String(255), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class AdPayment(Base):
    """A paid Stripe invoice for an advertiser's subscription: the money the
    network actually collected for ad time. Only recurring (ad placement)
    lines count; one time fees such as the maintenance fee are left out."""

    __tablename__ = "ad_payments"

    invoice_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    subscription_id: Mapped[str | None] = mapped_column(String(255), index=True)
    amount: Mapped[int] = mapped_column(Integer)  # recurring lines only, cents
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    livemode: Mapped[bool] = mapped_column(default=True)


class Host(Base):
    """A business that hosts screens. It earns `share_percent` of the ad
    revenue its screens play, sees it on a private page (/host/<token>) and is
    paid through Stripe Connect."""

    __tablename__ = "hosts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))  # contact person
    business_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    share_percent: Mapped[int] = mapped_column(Integer, default=20)
    # The secret in the host's private link. Only the owner (admin) can read
    # it; resetting it makes the old link stop working.
    access_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    stripe_account_id: Mapped[str | None] = mapped_column(String(255))
    payouts_enabled: Mapped[bool] = mapped_column(default=False)
    devices: Mapped[list["Device"]] = relationship(back_populates="host")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HostPayout(Base):
    """Money sent to a host for one calendar month (Stripe transfer)."""

    __tablename__ = "host_payouts"
    __table_args__ = (UniqueConstraint("host_id", "month", name="uq_host_payout_month"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), index=True)
    month: Mapped[date] = mapped_column(Date)  # first day of the month
    amount: Mapped[int] = mapped_column(Integer)  # cents
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    stripe_transfer_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
