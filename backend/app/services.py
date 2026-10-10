import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import schemas
from .config import settings
from .models import ApprovalStatus, Device, Loop, LoopItem, Media, MediaKind, Setting

FILES_PREFIX = "/files"


# --- Settings -----------------------------------------------------------------


def get_auto_approve(db: Session) -> bool:
    row = db.get(Setting, "auto_approve")
    return row is None or row.value == "true"  # default: on


def set_auto_approve(db: Session, value: bool) -> None:
    row = db.get(Setting, "auto_approve") or Setting(key="auto_approve", value="")
    row.value = "true" if value else "false"
    db.add(row)
    db.commit()


# --- Media --------------------------------------------------------------------


def file_url(filename: str | None) -> str | None:
    return f"{FILES_PREFIX}/{filename}" if filename else None


def media_out(media: Media, used_in_loops: int = 0) -> schemas.MediaOut:
    out = schemas.MediaOut.model_validate(media)
    out.url = file_url(media.filename)
    out.thumbnail_url = file_url(media.thumbnail_filename) or (
        out.url if media.kind is MediaKind.image else None
    )
    out.used_in_loops = used_in_loops
    return out


def loop_usage_counts(db: Session) -> dict:
    rows = db.execute(
        select(LoopItem.media_id, func.count(func.distinct(LoopItem.loop_id))).group_by(
            LoopItem.media_id
        )
    )
    return dict(rows.all())


# --- Loops --------------------------------------------------------------------


def load_loop(db: Session, loop_id) -> Loop | None:
    return db.scalar(
        select(Loop)
        .where(Loop.id == loop_id)
        .options(
            selectinload(Loop.items).selectinload(LoopItem.media),
            selectinload(Loop.devices),
        )
    )


def loop_out(loop: Loop) -> schemas.LoopOut:
    return schemas.LoopOut(
        id=loop.id,
        name=loop.name,
        items=[
            schemas.LoopItemOut(
                id=item.id,
                media_id=item.media_id,
                position=item.position,
                duration_seconds=item.duration_seconds,
                video_fit=item.video_fit,
                media=media_out(item.media),
            )
            for item in loop.items
        ],
        device_ids=[d.id for d in loop.devices],
        total_seconds=sum(i.duration_seconds for i in loop.items),
        updated_at=loop.updated_at,
    )


# --- Manifest -----------------------------------------------------------------

EMPTY_MANIFEST_VERSION = hashlib.sha256(b"empty").hexdigest()


def build_manifest(db: Session, loop_id) -> schemas.Manifest:
    loop = load_loop(db, loop_id) if loop_id else None
    if loop is None:
        return schemas.Manifest(
            version=EMPTY_MANIFEST_VERSION, loop_id=None, loop_name=None, items=[]
        )

    items: list[schemas.ManifestItem] = []
    for item in loop.items:
        media = item.media
        if media.status is not ApprovalStatus.approved:
            continue  # only approved content ever reaches a screen
        entry = schemas.ManifestItem(
            item_id=item.id,
            media_id=media.id,
            kind=media.kind,
            title=media.title,
            duration_seconds=item.duration_seconds,
            video_fit=item.video_fit,
        )
        if media.kind is MediaKind.text:
            entry.text = schemas.TextSlideProps(
                text=media.text or "",
                font_size=media.font_size or 96,
                text_color=media.text_color or "#FFFFFF",
                background_color=media.background_color or "#000000",
            )
        else:
            entry.url = file_url(media.filename)
            entry.sha256 = media.sha256
            entry.size_bytes = media.size_bytes
            entry.media_duration_seconds = media.duration_seconds
            entry.width = media.width
            entry.height = media.height
        items.append(entry)

    payload = json.dumps(
        {
            "loop": str(loop.id),
            "name": loop.name,
            "items": [i.model_dump(mode="json") for i in items],
        },
        sort_keys=True,
    )
    return schemas.Manifest(
        version=hashlib.sha256(payload.encode()).hexdigest(),
        loop_id=loop.id,
        loop_name=loop.name,
        items=items,
    )


# --- Devices ------------------------------------------------------------------


def is_online(device: Device, now: datetime | None = None) -> bool:
    if device.last_seen_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now - device.last_seen_at <= timedelta(seconds=settings.offline_after_seconds)


def device_out(db: Session, device: Device, now: datetime | None = None) -> schemas.DeviceOut:
    expected = build_manifest(db, device.loop_id).version
    return schemas.DeviceOut(
        id=device.id,
        device_uid=device.device_uid,
        name=device.name,
        venue_name=device.venue_name,
        venue_address=device.venue_address,
        latitude=device.latitude,
        longitude=device.longitude,
        location_accuracy_m=device.location_accuracy_m,
        location_at=device.location_at,
        online=is_online(device, now),
        last_seen_at=device.last_seen_at,
        battery_level=device.battery_level,
        is_charging=device.is_charging,
        app_version=device.app_version,
        now_playing_title=device.now_playing_title,
        now_playing_media_id=device.now_playing_media_id,
        loop_id=device.loop_id,
        loop_name=device.loop.name if device.loop else None,
        in_sync=device.manifest_version == expected,
        paired_at=device.paired_at,
    )
