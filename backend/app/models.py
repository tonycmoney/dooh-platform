import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Media(Base):
    __tablename__ = "media"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[MediaKind] = mapped_column(Enum(MediaKind, name="media_kind"))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"), default=ApprovalStatus.pending
    )

    # Files (images and videos)
    filename: Mapped[str | None] = mapped_column(String(300))
    original_name: Mapped[str | None] = mapped_column(String(300))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    thumbnail_filename: Mapped[str | None] = mapped_column(String(300))

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


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
