"""QR scan tracking.

Each ad's QR code points at a short link, /s/<code>. Opening it records the
scan and redirects the phone to the real destination (usually directions on
Google Maps), so advertisers can be shown how many people scanned their ad.
"""

import secrets
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import schemas
from ..config import settings
from ..db import get_db
from ..models import Media, QrLink, QrScan, utcnow
from ..security import require_admin, sha256_hex

public = APIRouter(tags=["scans"])
admin = APIRouter(prefix="/api/admin/qr-links", tags=["scans"], dependencies=[Depends(require_admin)])

# Link previews and crawlers open links without a person scanning anything.
BOT = re.compile(r"bot|crawl|spider|preview|facebookexternalhit|slurp|whatsapp|telegram|discord|curl|wget|python-requests|headless", re.I)
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i


def _new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(6))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@public.get("/s/{code}", include_in_schema=False)
def scan(code: str, request: Request, db: Session = Depends(get_db)):
    link = db.scalar(select(QrLink).where(QrLink.code == code))
    if not link:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    agent = request.headers.get("user-agent", "")
    if link.active and not BOT.search(agent):
        today = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
        visitor = sha256_hex(f"{settings.secret_key}|{today}|{_client_ip(request)}|{agent}")
        db.add(QrScan(link_id=link.id, visitor=visitor))
        db.commit()
    response = RedirectResponse(link.target_url, status_code=status.HTTP_302_FOUND)
    response.headers["Cache-Control"] = "no-store"
    return response


def _base_url(request: Request) -> str:
    return (settings.public_url or str(request.base_url)).rstrip("/")


def _out(db: Session, links: list[QrLink], request: Request) -> list[schemas.QrLinkOut]:
    if not links:
        return []
    ids = [link.id for link in links]
    now = utcnow()
    week, month = now - timedelta(days=7), now - timedelta(days=30)
    rows = db.execute(
        select(
            QrScan.link_id,
            func.count(),
            func.count().filter(QrScan.scanned_at >= week),
            func.count().filter(QrScan.scanned_at >= month),
            func.count(func.distinct(QrScan.visitor)).filter(QrScan.scanned_at >= month),
            func.max(QrScan.scanned_at),
        )
        .where(QrScan.link_id.in_(ids))
        .group_by(QrScan.link_id)
    ).all()
    stats = {r[0]: r[1:] for r in rows}
    media_ids = [link.media_id for link in links if link.media_id]
    titles = dict(db.execute(select(Media.id, Media.title).where(Media.id.in_(media_ids))).all()) if media_ids else {}
    base = _base_url(request)
    out = []
    for link in links:
        total, d7, d30, u30, last = stats.get(link.id, (0, 0, 0, 0, None))
        out.append(schemas.QrLinkOut(
            id=link.id, code=link.code, label=link.label, target_url=link.target_url,
            short_url=f"{base}/s/{link.code}", media_id=link.media_id,
            media_title=titles.get(link.media_id), active=link.active, created_at=link.created_at,
            scans_total=total, scans_7d=d7, scans_30d=d30, unique_30d=u30, last_scan_at=last,
        ))
    return out


def _get(db: Session, link_id: uuid.UUID) -> QrLink:
    link = db.get(QrLink, link_id)
    if not link:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "QR link not found")
    return link


@admin.get("", response_model=list[schemas.QrLinkOut])
def list_links(request: Request, db: Session = Depends(get_db)):
    links = list(db.scalars(select(QrLink).order_by(QrLink.label)))
    return _out(db, links, request)


@admin.post("", response_model=schemas.QrLinkOut, status_code=201)
def create_link(body: schemas.QrLinkIn, request: Request, db: Session = Depends(get_db)):
    for _ in range(5):
        link = QrLink(code=body.code or _new_code(), label=body.label, target_url=body.target_url, media_id=body.media_id)
        db.add(link)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if body.code:
                raise HTTPException(status.HTTP_409_CONFLICT, "That code is already used")
    else:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not make a unique code")
    return _out(db, [link], request)[0]


@admin.patch("/{link_id}", response_model=schemas.QrLinkOut)
def update_link(link_id: uuid.UUID, body: schemas.QrLinkUpdate, request: Request, db: Session = Depends(get_db)):
    link = _get(db, link_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(link, field, value)
    db.commit()
    return _out(db, [link], request)[0]


@admin.delete("/{link_id}", status_code=204)
def delete_link(link_id: uuid.UUID, db: Session = Depends(get_db)):
    db.delete(_get(db, link_id))
    db.commit()


@admin.get("/{link_id}/daily", response_model=list[schemas.QrDay])
def daily(link_id: uuid.UUID, days: int = Query(30, ge=1, le=366), db: Session = Depends(get_db)):
    _get(db, link_id)
    tz = ZoneInfo(settings.timezone)
    start = datetime.now(tz).date() - timedelta(days=days - 1)
    since = datetime.combine(start, datetime.min.time(), tz).astimezone(timezone.utc)
    local_day = func.date(func.timezone(settings.timezone, QrScan.scanned_at))
    rows = db.execute(
        select(local_day, func.count(), func.count(func.distinct(QrScan.visitor)))
        .where(QrScan.link_id == link_id, QrScan.scanned_at >= since)
        .group_by(local_day)
    ).all()
    by_day = {r[0]: (r[1], r[2]) for r in rows}
    return [
        schemas.QrDay(day=d, scans=by_day.get(d, (0, 0))[0], unique=by_day.get(d, (0, 0))[1])
        for d in (start + timedelta(days=i) for i in range(days))
    ]
