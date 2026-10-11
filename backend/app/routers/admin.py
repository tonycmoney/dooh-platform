"""Endpoints the control dashboard calls."""

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from .. import backups, schemas, services
from ..config import settings
from ..db import get_db
from ..formatting import FORMAT_VERSION, render_text
from ..media_files import (
    SUPPORTED_LABEL,
    apply_formatted,
    bad_request,
    delete_files,
    delete_originals,
    incoming_dir,
    kind_for,
    process_upload,
    reformat,
    restore_file,
)
from ..models import (
    ApprovalStatus,
    Device,
    FileStatus,
    FitMode,
    Loop,
    LoopItem,
    Media,
    MediaKind,
    PlayLog,
    WebsiteOrder,
)
from ..orders import attach_file, process_order_file
from ..security import (
    check_admin_password,
    create_admin_token,
    login_throttle,
    new_secret,
    require_admin,
    sha256_hex,
)

public = APIRouter(prefix="/api/admin", tags=["admin"])
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


MAX_UPLOAD_BYTES = 4 * 2**30


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


# --- Auth & settings ----------------------------------------------------------


@public.post("/login", response_model=schemas.LoginOut)
def login(body: schemas.LoginIn, request: Request):
    client = request.client.host if request.client else "unknown"
    if wait := login_throttle.retry_after(client):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many wrong passwords. Try again in {max(1, wait // 60)} min.",
            headers={"Retry-After": str(wait)},
        )
    if not check_admin_password(body.password):
        login_throttle.failed(client)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password")
    login_throttle.reset(client)
    return schemas.LoginOut(token=create_admin_token())


def _settings_out(db: Session) -> schemas.SettingsOut:
    return schemas.SettingsOut(
        auto_approve=services.get_auto_approve(db),
        maintenance_pin_set=services.get_maintenance_pin(db) is not None,
    )


@router.get("/settings", response_model=schemas.SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return _settings_out(db)


@router.put("/settings", response_model=schemas.SettingsOut)
def put_settings(body: schemas.SettingsIn, db: Session = Depends(get_db)):
    services.set_auto_approve(db, body.auto_approve)
    return _settings_out(db)


@router.put("/maintenance-pin", response_model=schemas.SettingsOut)
def set_maintenance_pin(body: schemas.MaintenancePinIn, db: Session = Depends(get_db)):
    """Sets the PIN for the tablets' hidden maintenance panel. Tablets pick
    it up with their next heartbeat (within a minute)."""
    services.set_maintenance_pin(db, body.pin)
    return _settings_out(db)


@router.delete("/maintenance-pin", response_model=schemas.SettingsOut)
def clear_maintenance_pin(db: Session = Depends(get_db)):
    services.set_maintenance_pin(db, None)
    return _settings_out(db)


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


async def _receive_upload(request: Request) -> tuple[Path, str, str | None]:
    """Accepts either a raw body (Content-Type = file type, X-Filename header,
    used by the dashboard) or multipart/form-data with the file in any field
    (`file` preferred). Returns (saved path, original filename, title)."""
    def incoming_path(name: str) -> Path:
        # Keep the extension: converters pick the reader from it.
        return incoming_dir() / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"

    content_type = request.headers.get("content-type", "")
    title = None

    if content_type.startswith("multipart/form-data"):
        form = await request.form(max_files=1, max_fields=10)
        uploads = [v for _, v in form.multi_items() if isinstance(v, StarletteUploadFile)]
        upload = next((v for k, v in form.multi_items() if k == "file" and isinstance(v, StarletteUploadFile)), None)
        upload = upload or (uploads[0] if uploads else None)
        if upload is None:
            fields = ", ".join(sorted(form.keys())) or "none"
            raise bad_request(
                f"No file was received (form fields: {fields}). Choose the file again, "
                f"or export it from Photos first. Supported: {SUPPORTED_LABEL}."
            )
        filename = upload.filename or ""
        kind_for(filename)  # reject unsupported types before saving anything
        title = form.get("title") if isinstance(form.get("title"), str) else None
        incoming = incoming_path(filename)
        with incoming.open("wb") as out:
            while chunk := await upload.read(1024 * 1024):
                out.write(chunk)
        await upload.close()
    else:
        filename = unquote(request.headers.get("x-filename", "")).strip()
        if not filename:
            raise bad_request("Missing file name (X-Filename header).")
        kind_for(filename)
        title = unquote(request.headers.get("x-title", "")).strip() or None
        incoming = incoming_path(filename)
        size = 0
        with incoming.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    out.close()
                    incoming.unlink(missing_ok=True)
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        f"“{filename}” is larger than {MAX_UPLOAD_BYTES // 2**30} GB.",
                    )
                out.write(chunk)
    return incoming, Path(filename).name, title


@router.post("/media", response_model=schemas.MediaOut, status_code=201)
async def upload_media(request: Request, db: Session = Depends(get_db)):
    """Upload an image (JPG, PNG, HEIC) or video (MP4, MOV). The original is
    kept; screens get a 1080x1920 formatted copy with a white border."""
    incoming, filename, title = await _receive_upload(request)
    try:
        stored = await run_in_threadpool(process_upload, incoming, filename)
    finally:
        incoming.unlink(missing_ok=True)
    default_title = filename.rsplit(".", 1)[0] or "Untitled"
    media = Media(
        kind=stored.kind,
        title=(title or default_title).strip()[:300] or "Untitled",
        status=_initial_status(db),
        original_name=filename,
        source_filename=stored.source_filename,
        source_sha256=stored.source_sha256,
        source_size_bytes=stored.source_size_bytes,
        source_width=stored.source_width,
        source_height=stored.source_height,
        fit_mode=FitMode.fit,
    )
    apply_formatted(media, stored.formatted, FORMAT_VERSION)
    db.add(media)
    try:
        db.commit()
    except BaseException:
        delete_files(stored.formatted.filename, stored.formatted.thumbnail_filename)
        delete_originals(stored.source_filename)
        raise
    return services.media_out(media)


@router.put("/media/{media_id}/file", response_model=schemas.MediaOut)
async def restore_media_file(
    media_id: uuid.UUID, request: Request, original: bool = False, db: Session = Depends(get_db)
):
    """Puts back the formatted file (or with ?original=true, the original) of
    an existing item, after moving servers or losing the volume. The body
    must be the exact file: its SHA-256 has to match the recorded one."""
    media = _get_media(db, media_id)
    incoming = incoming_dir() / f"{uuid.uuid4().hex}.restore"
    try:
        size = 0
        with incoming.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File too large.")
                out.write(chunk)
        await run_in_threadpool(restore_file, incoming, media, original=original)
    finally:
        incoming.unlink(missing_ok=True)
    return services.media_out(media)


def _reformat_and_commit(db: Session, media: Media) -> None:
    """Makes the new formatted file, commits, then removes the old one, so a
    screen is never pointed at a file that doesn't exist yet or anymore."""
    old_files = reformat(media)
    try:
        db.commit()
    except BaseException:
        delete_files(media.filename, media.thumbnail_filename)
        raise
    delete_files(*old_files)


@router.post("/text-slides", response_model=schemas.MediaOut, status_code=201)
def create_text_slide(body: schemas.TextSlideIn, db: Session = Depends(get_db)):
    media = Media(kind=MediaKind.text, status=_initial_status(db), **body.model_dump())
    db.add(media)
    _reformat_and_commit(db, media)
    return services.media_out(media)


@router.put("/text-slides/{media_id}", response_model=schemas.MediaOut)
def update_text_slide(media_id: uuid.UUID, body: schemas.TextSlideIn, db: Session = Depends(get_db)):
    media = _get_media(db, media_id)
    if media.kind is not MediaKind.text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a text slide")
    for key, value in body.model_dump().items():
        setattr(media, key, value)
    _reformat_and_commit(db, media)
    return services.media_out(media)


@router.post("/text-slides/preview", response_class=Response,
             responses={200: {"content": {"image/jpeg": {}}}})
def preview_text_slide(body: schemas.TextSlideIn):
    """The exact 1080x1920 image a text slide will be, without saving it."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "preview.jpg"
        render_text(body.text, body.text_color, body.background_color, target)
        return Response(target.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.patch("/media/{media_id}", response_model=schemas.MediaOut)
def update_media(media_id: uuid.UUID, body: schemas.MediaUpdate, db: Session = Depends(get_db)):
    """Rename, or switch between Fit and Fill (which reformats the item)."""
    media = _get_media(db, media_id)
    if body.title:
        media.title = body.title
    if body.fit_mode is not None and body.fit_mode is not media.fit_mode:
        if media.kind is MediaKind.text:
            raise bad_request("Text slides are always sized to fit.")
        media.fit_mode = body.fit_mode
        _reformat_and_commit(db, media)
    else:
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
    files, original = (media.filename, media.thumbnail_filename), media.source_filename
    db.delete(media)  # loop items cascade
    db.commit()
    delete_files(*files)
    delete_originals(original)


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
    replaced = None
    if body.replaces_device_id:
        replaced = _get_device(db, body.replaces_device_id)
        if replaced.id == device.id:
            raise bad_request("A tablet can't replace itself.")

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
    if replaced is not None:
        # Keep the screen's history and settings under the new tablet.
        db.execute(update(PlayLog).where(PlayLog.device_id == replaced.id).values(device_id=device.id))
        if not body.loop_id:
            device.loop_id = replaced.loop_id
        for field in ("latitude", "longitude", "location_accuracy_m", "location_at"):
            if getattr(device, field) is None:
                setattr(device, field, getattr(replaced, field))
        db.delete(replaced)
    db.commit()
    db.refresh(device)
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
        # Website orders waiting on you: to approve, a failed file, or an ad to design.
        "orders_to_review": db.scalar(
            select(func.count()).select_from(WebsiteOrder).outerjoin(Media, WebsiteOrder.media_id == Media.id)
            .where(
                (Media.status == ApprovalStatus.pending)
                | (WebsiteOrder.file_status == FileStatus.failed)
                | ((WebsiteOrder.file_status == FileStatus.none) & WebsiteOrder.media_id.is_(None))
            )
        ),
    }


# --- Backups ------------------------------------------------------------------


def _backup_out(b: backups.Backup) -> schemas.BackupOut:
    return schemas.BackupOut(name=b.name, size_bytes=b.size_bytes, created_at=b.created_at)


@router.get("/backups", response_model=schemas.BackupsOut)
def list_backups():
    return schemas.BackupsOut(
        daily_enabled=settings.daily_backups,
        keep_days=settings.backup_keep_days,
        backups=[_backup_out(b) for b in backups.list_backups()],
    )


@router.post("/backups", response_model=schemas.BackupOut, status_code=201)
async def backup_now():
    try:
        return _backup_out(await run_in_threadpool(backups.run_backup))
    except RuntimeError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from e


@router.get("/backups/{name}")
def download_backup(name: str):
    path = backups.backup_path(name)
    if path is None:
        raise _not_found("Backup")
    return FileResponse(path, media_type="application/octet-stream", filename=name)


# --- Website orders -----------------------------------------------------------


def _order_out(order: WebsiteOrder) -> schemas.OrderOut:
    return schemas.OrderOut(
        **{f: getattr(order, f) for f in schemas.OrderOut.model_fields if f not in ("media", "can_retry")},
        can_retry=order.file_status is FileStatus.failed and bool(order.file_url),
        media=services.media_out(order.media) if order.media else None,
    )


def _get_order(db: Session, order_id: uuid.UUID) -> WebsiteOrder:
    order = db.get(WebsiteOrder, order_id)
    if order is None:
        raise _not_found("Order")
    return order


@router.get("/orders", response_model=list[schemas.OrderOut])
def list_orders(db: Session = Depends(get_db)):
    query = (select(WebsiteOrder).options(selectinload(WebsiteOrder.media))
             .order_by(WebsiteOrder.created_at.desc()).limit(500))
    return [_order_out(o) for o in db.scalars(query)]


@router.post("/orders/{order_id}/file", response_model=schemas.OrderOut)
async def attach_order_file(order_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """Adds the ad you made for a "Design it for me" order (or a corrected
    file). Like every website ad, it waits for approval."""
    order = _get_order(db, order_id)
    incoming, filename, _ = await _receive_upload(request)
    try:
        await run_in_threadpool(attach_file, order, incoming, filename, db)
    finally:
        incoming.unlink(missing_ok=True)
    db.refresh(order)
    return _order_out(order)


@router.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """Removes a spam or test order, and its ad unless it's approved (an
    approved ad stays in the media library)."""
    order = _get_order(db, order_id)
    media = order.media if order.media and order.media.status is not ApprovalStatus.approved else None
    files = (media.filename, media.thumbnail_filename, media.source_filename) if media else ()
    db.delete(order)
    if media:
        db.delete(media)
    db.commit()
    if files:
        delete_files(files[0], files[1])
        delete_originals(files[2])


@router.post("/orders/{order_id}/retry", response_model=schemas.OrderOut)
def retry_order_file(order_id: uuid.UUID, background: BackgroundTasks, db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    if order.file_status is not FileStatus.failed or not order.file_url:
        raise bad_request("There's no failed download to retry.")
    order.file_status = FileStatus.queued
    order.file_error = None
    db.commit()
    background.add_task(process_order_file, order.id)
    return _order_out(order)
