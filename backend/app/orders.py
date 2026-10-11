"""Ad orders from the customer website.

The website posts the order with a signed download link to the ad file. The
order is stored at once (so checkout never waits); the file is downloaded and
formatted in the background, and becomes a media item that always waits in
the approval queue: nothing from the website plays until an admin approves it.
"""

import logging
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .formatting import FORMAT_VERSION
from .media_files import (
    apply_formatted,
    delete_files,
    delete_originals,
    incoming_dir,
    kind_for,
    process_upload,
)
from .models import ApprovalStatus, FileStatus, Media, WebsiteOrder

log = logging.getLogger("dooh.orders")

DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, read=120.0)


def allowed_file_host(url: str) -> bool:
    """HTTPS links to the configured storage hosts only (no other servers,
    no internal addresses)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    suffixes = [s.strip().lower() for s in settings.order_file_hosts.split(",") if s.strip()]
    return (
        parts.scheme == "https"
        and not parts.username
        and any(host == s.lstrip(".") or (s.startswith(".") and host.endswith(s)) for s in suffixes)
    )


def check_file(url: str, file_name: str) -> None:
    """Rejects a file the server would refuse anyway, while the website is
    still waiting for the answer. Raises HTTPException(400)."""
    if not allowed_file_host(url):
        raise HTTPException(400, f"file_url must be an https link to {settings.order_file_hosts}")
    kind_for(file_name)  # readable error for e.g. a PDF


def download(url: str, target: Path) -> None:
    """Streams the file to `target`. Raises ValueError with a readable reason."""
    if not allowed_file_host(url):
        raise ValueError("The file link isn't an allowed storage address.")
    size = 0
    try:
        with httpx.stream("GET", url, timeout=DOWNLOAD_TIMEOUT, follow_redirects=False) as res:
            if res.status_code != 200:
                raise ValueError(f"Downloading the file failed (HTTP {res.status_code}); the link may have expired.")
            with target.open("wb") as out:
                for chunk in res.iter_bytes(1 << 20):
                    size += len(chunk)
                    if size > settings.order_file_max_bytes:
                        limit = max(1, round(settings.order_file_max_bytes / 2**20))
                        raise ValueError(f"The file is larger than {limit} MB.")
                    out.write(chunk)
    except httpx.HTTPError as e:
        raise ValueError(f"Downloading the file failed: {e.__class__.__name__}") from e


def media_title(order: WebsiteOrder) -> str:
    return f"{order.business_name} · {order.external_id}"[:300]


def attach_file(order: WebsiteOrder, incoming: Path, original_name: str, db) -> Media:
    """Formats a received file and links it to the order as a pending item.
    Consumes `incoming`. Raises HTTPException(400) for unusable files."""
    stored = process_upload(incoming, original_name)
    media = Media(
        kind=stored.kind,
        title=media_title(order),
        status=ApprovalStatus.pending,  # website ads always need approval
        original_name=original_name,
        source_filename=stored.source_filename,
        source_sha256=stored.source_sha256,
        source_size_bytes=stored.source_size_bytes,
        source_width=stored.source_width,
        source_height=stored.source_height,
    )
    apply_formatted(media, stored.formatted, FORMAT_VERSION)
    db.add(media)
    db.flush()
    order.media_id = media.id
    order.file_status = FileStatus.ready
    order.file_error = None
    order.file_url = None
    try:
        db.commit()
    except BaseException:
        delete_files(stored.formatted.filename, stored.formatted.thumbnail_filename)
        delete_originals(stored.source_filename)
        raise
    return media


def process_order_file(order_id: uuid.UUID) -> None:
    """Background job: download the order's file and add it to the approval
    queue. Failures are recorded on the order for the dashboard."""
    with SessionLocal() as db:
        order = db.get(WebsiteOrder, order_id)
        if order is None or order.file_status is not FileStatus.queued or not order.file_url:
            return
        name = Path(order.file_name or "ad").name
        incoming = incoming_dir() / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
        try:
            download(order.file_url, incoming)
            attach_file(order, incoming, name, db)
            log.info("Website order %s: file ready for approval", order.external_id)
        except (ValueError, HTTPException) as e:
            db.rollback()
            order = db.get(WebsiteOrder, order_id)
            order.file_status = FileStatus.failed
            order.file_error = e.detail if isinstance(e, HTTPException) else str(e)
            db.commit()
            log.warning("Website order %s: %s", order.external_id, order.file_error)
        finally:
            incoming.unlink(missing_ok=True)


def resume_queued() -> None:
    """After a restart, finish files that were still waiting."""
    with SessionLocal() as db:
        ids = db.scalars(select(WebsiteOrder.id).where(WebsiteOrder.file_status == FileStatus.queued)).all()
    if ids:
        log.info("Resuming %d queued website order file(s)", len(ids))
        threading.Thread(target=lambda: [process_order_file(i) for i in ids], daemon=True).start()

