"""Endpoints the tablet calls."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import schemas, services
from ..db import get_db
from ..models import Device, PlayLog
from ..security import new_pairing_code, new_secret, require_device, sha256_hex

router = APIRouter(prefix="/api/player", tags=["player"])


@router.post("/register", response_model=schemas.RegisterOut)
def register(body: schemas.RegisterIn, db: Session = Depends(get_db)):
    """Called by an unpaired tablet. Returns a fresh code to show on screen.

    Re-registering an already-paired tablet (e.g. after a reinstall wiped its
    token) keeps its name, venue and loop, but it must be paired again.
    """
    device = db.scalar(select(Device).where(Device.device_uid == body.device_uid))
    if device is None:
        device = Device(device_uid=body.device_uid)
        db.add(device)

    claim_secret = new_secret()
    device.claim_secret_hash = sha256_hex(claim_secret)
    device.pending_token = None
    device.token_hash = None
    device.app_version = body.app_version or device.app_version

    for _ in range(10):
        device.pairing_code = new_pairing_code()
        try:
            db.commit()
            break
        except IntegrityError:  # code collision, try another
            db.rollback()
            db.add(device)
    else:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Try again")

    return schemas.RegisterOut(pairing_code=device.pairing_code, claim_secret=claim_secret)


@router.post("/pairing-status", response_model=schemas.PairingStatusOut)
def pairing_status(body: schemas.PairingStatusIn, db: Session = Depends(get_db)):
    """Polled by the tablet while it shows its code. Hands over the device
    token exactly once, after the admin has entered the code."""
    device = db.scalar(select(Device).where(Device.device_uid == body.device_uid))
    if device is None or device.claim_secret_hash != sha256_hex(body.claim_secret):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown registration; register again")

    if device.pending_token is None:
        return schemas.PairingStatusOut(paired=False)

    token = device.pending_token
    device.pending_token = None
    device.claim_secret_hash = None
    db.commit()
    return schemas.PairingStatusOut(
        paired=True,
        token=token,
        device_id=device.id,
        name=device.name,
        venue_name=device.venue_name,
    )


@router.get("/manifest", response_model=schemas.Manifest)
def manifest(device: Device = Depends(require_device), db: Session = Depends(get_db)):
    return services.build_manifest(db, device.loop_id)


@router.post("/heartbeat", response_model=schemas.HeartbeatOut)
def heartbeat(
    body: schemas.HeartbeatIn,
    device: Device = Depends(require_device),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    device.last_seen_at = now
    if body.app_version:
        device.app_version = body.app_version
    if body.battery_level is not None:
        device.battery_level = body.battery_level
    if body.is_charging is not None:
        device.is_charging = body.is_charging
    if body.latitude is not None and body.longitude is not None:
        device.latitude = body.latitude
        device.longitude = body.longitude
        device.location_accuracy_m = body.location_accuracy_m
        device.location_at = now
    device.now_playing_media_id = body.now_playing_media_id
    device.now_playing_title = body.now_playing_title
    if body.manifest_version:
        device.manifest_version = body.manifest_version
    db.commit()

    return schemas.HeartbeatOut(
        manifest_version=services.build_manifest(db, device.loop_id).version,
        name=device.name,
        venue_name=device.venue_name,
    )


@router.post("/plays", response_model=schemas.PlaysOut)
def log_plays(
    body: schemas.PlaysIn,
    device: Device = Depends(require_device),
    db: Session = Depends(get_db),
):
    """Proof of play. Idempotent: plays are keyed by the tablet-generated id,
    so a batch that is retried after a network error is not double-counted."""
    if not body.plays:
        return schemas.PlaysOut(accepted=[], inserted=0)
    rows = [
        {
            "id": p.id,
            "device_id": device.id,
            "media_id": p.media_id,
            "media_title": p.media_title,
            "loop_id": p.loop_id,
            "started_at": p.started_at,
            "duration_ms": p.duration_ms,
            "received_at": datetime.now(timezone.utc),
        }
        for p in body.plays
    ]
    inserted = db.scalars(
        insert(PlayLog)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(PlayLog.id)
    ).all()
    db.commit()
    return schemas.PlaysOut(accepted=[p.id for p in body.plays], inserted=len(inserted))
