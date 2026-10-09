"""Endpoints the control dashboard calls."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from .. import schemas, services
from ..db import get_db
from ..media_files import delete_files, store_upload
from ..models import ApprovalStatus, Device, Loop, LoopItem, Media, MediaKind, PlayLog
from ..security import check_admin_password, create_admin_token, new_secret, require_admin, sha256_hex

public = APIRouter(prefix="/api/admin", tags=["admin"])
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


# --- Auth & settings ----------------------------------------------------------


@public.post("/login", response_model=schemas.LoginOut)
def login(body: schemas.LoginIn):
    if not check_admin_password(body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password")
    return schemas.LoginOut(token=create_admin_token())


@router.get("/settings", response_model=schemas.SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return schemas.SettingsOut(auto_approve=services.get_auto_approve(db))


@router.put("/settings", response_model=schemas.SettingsOut)
def put_settings(body: schemas.SettingsIn, db: Session = Depends(get_db)):
    services.set_auto_approve(db, body.auto_approve)
    return schemas.SettingsOut(auto_approve=body.auto_approve)


# --- Media --------------------------------------------------------------------


def _get_media(db: Session, media_id: uuid.UUID) -> Media:
    media = db.get(Media, media_id)
    if media is None:
        raise _not_found("Media")
    return media


def _initial_status(db: Session) -> ApprovalStatus:
    return ApprovalStatus.approved if services.get_auto_approve(db) else ApprovalStatus.pending


@router.get("/media", response_model=list[schemas.MediaOut])
def list_media(
    status_filter: ApprovalStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    query = select(Media).order_by(Media.created_at.desc())
    if status_filter:
        query = query.where(Media.status == status_filter)
    usage = services.loop_usage_counts(db)
    return [services.media_out(m, usage.get(m.id, 0)) for m in db.scalars(query)]


@router.post("/media", response_model=schemas.MediaOut, status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    stored = await store_upload(file)
    default_title = (file.filename or "Untitled").rsplit(".", 1)[0]
    media = Media(
        kind=stored.kind,
        title=(title or default_title).strip()[:300] or "Untitled",
        status=_initial_status(db),
        filename=stored.filename,
        original_name=file.filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        width=stored.width,
        height=stored.height,
        duration_seconds=stored.duration_seconds,
        thumbnail_filename=stored.thumbnail_filename,
    )
    db.add(media)
    db.commit()
    return services.media_out(media)


@router.post("/text-slides", response_model=schemas.MediaOut, status_code=201)
def create_text_slide(body: schemas.TextSlideIn, db: Session = Depends(get_db)):
    media = Media(kind=MediaKind.text, status=_initial_status(db), **body.model_dump())
    db.add(media)
    db.commit()
    return services.media_out(media)


@router.put("/text-slides/{media_id}", response_model=schemas.MediaOut)
def update_text_slide(media_id: uuid.UUID, body: schemas.TextSlideIn, db: Session = Depends(get_db)):
    media = _get_media(db, media_id)
    if media.kind is not MediaKind.text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a text slide")
    for key, value in body.model_dump().items():
        setattr(media, key, value)
    db.commit()
    return services.media_out(media)


@router.patch("/media/{media_id}", response_model=schemas.MediaOut)
def rename_media(media_id: uuid.UUID, body: schemas.MediaUpdate, db: Session = Depends(get_db)):
    media = _get_media(db, media_id)
    if body.title:
        media.title = body.title
    db.commit()
    return services.media_out(media)


@router.post("/media/{media_id}/approve", response_model=schemas.MediaOut)
def approve_media(media_id: uuid.UUID, db: Session = Depends(get_db)):
    media = _get_media(db, media_id)
    media.status = ApprovalStatus.approved
    db.commit()
    return services.media_out(media)


@router.post("/media/{media_id}/reject", response_model=schemas.MediaOut)
def reject_media(media_id: uuid.UUID, db: Session = Depends(get_db)):
    media = _get_media(db, media_id)
    media.status = ApprovalStatus.rejected
    db.commit()
    return services.media_out(media)


@router.delete("/media/{media_id}", status_code=204)
def delete_media(media_id: uuid.UUID, db: Session = Depends(get_db)):
    media = _get_media(db, media_id)
    files = (media.filename, media.thumbnail_filename)
    db.delete(media)  # loop items cascade
    db.commit()
    delete_files(*files)


# --- Loops --------------------------------------------------------------------


def _replace_items(db: Session, loop: Loop, items: list[schemas.LoopItemIn]) -> None:
    media_ids = {i.media_id for i in items}
    found = set(db.scalars(select(Media.id).where(Media.id.in_(media_ids)))) if media_ids else set()
    missing = media_ids - found
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown media: {sorted(map(str, missing))}")
    loop.items.clear()
    db.flush()
    for position, item in enumerate(items):
        loop.items.append(
            LoopItem(
                media_id=item.media_id,
                position=position,
                duration_seconds=item.duration_seconds,
                video_fit=item.video_fit,
            )
        )
    loop.updated_at = datetime.now(timezone.utc)


def _get_loop(db: Session, loop_id: uuid.UUID) -> Loop:
    loop = services.load_loop(db, loop_id)
    if loop is None:
        raise _not_found("Loop")
    return loop


@router.get("/loops", response_model=list[schemas.LoopSummary])
def list_loops(db: Session = Depends(get_db)):
    loops = db.scalars(
        select(Loop)
        .options(selectinload(Loop.items), selectinload(Loop.devices))
        .order_by(Loop.updated_at.desc())
    )
    return [
        schemas.LoopSummary(
            id=loop.id,
            name=loop.name,
            item_count=len(loop.items),
            total_seconds=sum(i.duration_seconds for i in loop.items),
            device_count=len(loop.devices),
            updated_at=loop.updated_at,
        )
        for loop in loops
    ]


@router.post("/loops", response_model=schemas.LoopOut, status_code=201)
def create_loop(body: schemas.LoopIn, db: Session = Depends(get_db)):
    loop = Loop(name=body.name)
    db.add(loop)
    db.flush()
    _replace_items(db, loop, body.items)
    db.commit()
    return services.loop_out(_get_loop(db, loop.id))


@router.get("/loops/{loop_id}", response_model=schemas.LoopOut)
def get_loop(loop_id: uuid.UUID, db: Session = Depends(get_db)):
    return services.loop_out(_get_loop(db, loop_id))


@router.put("/loops/{loop_id}", response_model=schemas.LoopOut)
def update_loop(loop_id: uuid.UUID, body: schemas.LoopIn, db: Session = Depends(get_db)):
    """Replace the loop's name and full ordered item list (add/remove/reorder)."""
    loop = _get_loop(db, loop_id)
    loop.name = body.name
    _replace_items(db, loop, body.items)
    db.commit()
    db.expire_all()
    return services.loop_out(_get_loop(db, loop_id))


@router.delete("/loops/{loop_id}", status_code=204)
def delete_loop(loop_id: uuid.UUID, db: Session = Depends(get_db)):
    db.delete(_get_loop(db, loop_id))
    db.commit()


@router.put("/loops/{loop_id}/screens", response_model=schemas.LoopOut)
def assign_loop(loop_id: uuid.UUID, body: schemas.AssignIn, db: Session = Depends(get_db)):
    """Set exactly which screens play this loop."""
    _get_loop(db, loop_id)
    wanted = set(body.device_ids)
    db.execute(
        update(Device)
        .where(Device.loop_id == loop_id, Device.id.not_in(wanted) if wanted else True)
        .values(loop_id=None)
    )
    if wanted:
        db.execute(update(Device).where(Device.id.in_(wanted)).values(loop_id=loop_id))
    db.commit()
    db.expire_all()
    return services.loop_out(_get_loop(db, loop_id))


# --- Screens ------------------------------------------------------------------


def _get_device(db: Session, device_id: uuid.UUID) -> Device:
    device = db.get(Device, device_id)
    if device is None or device.paired_at is None:
        raise _not_found("Screen")
    return device


def _check_loop(db: Session, loop_id: uuid.UUID | None) -> None:
    if loop_id and db.get(Loop, loop_id) is None:
        raise _not_found("Loop")


@router.get("/screens", response_model=list[schemas.DeviceOut])
def list_screens(db: Session = Depends(get_db)):
    devices = db.scalars(
        select(Device)
        .where(Device.paired_at.is_not(None))
        .options(selectinload(Device.loop))
        .order_by(Device.name)
    )
    now = datetime.now(timezone.utc)
    return [services.device_out(db, d, now) for d in devices]


@router.post("/screens/pair", response_model=schemas.DeviceOut)
def pair_screen(body: schemas.PairIn, db: Session = Depends(get_db)):
    device = db.scalar(select(Device).where(Device.pairing_code == body.pairing_code))
    if device is None or device.claim_secret_hash is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No tablet is showing that code. Check the code on the tablet screen.",
        )
    _check_loop(db, body.loop_id)

    token = new_secret()
    device.token_hash = sha256_hex(token)
    device.pending_token = token  # collected once by the tablet, then cleared
    device.pairing_code = None
    device.paired_at = datetime.now(timezone.utc)
    device.name = body.name
    device.venue_name = body.venue_name
    device.venue_address = body.venue_address
    if body.loop_id:
        device.loop_id = body.loop_id
    db.commit()
    return services.device_out(db, device)


@router.patch("/screens/{device_id}", response_model=schemas.DeviceOut)
def update_screen(device_id: uuid.UUID, body: schemas.DeviceUpdate, db: Session = Depends(get_db)):
    device = _get_device(db, device_id)
    for field in ("name", "venue_name", "venue_address"):
        value = getattr(body, field)
        if value is not None:
            setattr(device, field, value)
    if body.clear_loop:
        device.loop_id = None
    elif body.loop_id:
        _check_loop(db, body.loop_id)
        device.loop_id = body.loop_id
    db.commit()
    db.refresh(device)
    return services.device_out(db, device)


@router.delete("/screens/{device_id}", status_code=204)
def unpair_screen(device_id: uuid.UUID, db: Session = Depends(get_db)):
    """Revoke the tablet's token. It will show a new pairing code."""
    device = _get_device(db, device_id)
    device.token_hash = None
    device.pending_token = None
    device.paired_at = None
    db.commit()


@router.get("/screens/{device_id}/plays", response_model=list[schemas.PlayLogOut])
def screen_plays(
    device_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _get_device(db, device_id)
    return db.scalars(
        select(PlayLog)
        .where(PlayLog.device_id == device_id)
        .order_by(PlayLog.started_at.desc())
        .limit(limit)
    ).all()


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "pending_approvals": db.scalar(
            select(func.count()).select_from(Media).where(Media.status == ApprovalStatus.pending)
        ),
        "plays_today": db.scalar(
            select(func.count()).select_from(PlayLog).where(PlayLog.started_at >= today)
        ),
    }
