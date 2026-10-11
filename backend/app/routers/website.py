"""Endpoint the customer website calls with new ad orders. Protected by a
shared secret (WEBSITE_API_KEY) sent as `Authorization: Bearer <key>`."""

import hmac
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import orders, schemas
from ..config import settings
from ..db import get_db
from ..models import FileStatus, WebsiteOrder
from ..security import LoginThrottle

router = APIRouter(prefix="/api/website", tags=["website"])

# Wrong keys are throttled like wrong dashboard passwords.
key_throttle = LoginThrottle(per_client=20, overall=200)


def require_website_key(request: Request, authorization: str | None = Header(default=None)) -> None:
    if not settings.website_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Website orders aren't set up on this server.")
    client = request.client.host if request.client else "unknown"
    if wait := key_throttle.retry_after(client):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many bad keys.",
                            headers={"Retry-After": str(wait)})
    token = (authorization or "")[7:].strip() if (authorization or "").lower().startswith("bearer ") else ""
    if not hmac.compare_digest(token.encode(), settings.website_api_key.encode()):
        key_throttle.failed(client)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid website API key")


def _accepted(order: WebsiteOrder, duplicate: bool) -> schemas.WebsiteOrderAccepted:
    return schemas.WebsiteOrderAccepted(order_id=order.external_id, duplicate=duplicate, file=order.file_status)


@router.post("/orders", response_model=schemas.WebsiteOrderAccepted, status_code=201,
             dependencies=[Depends(require_website_key)])
def create_order(body: schemas.WebsiteOrderIn, response: Response, background: BackgroundTasks,
                 db: Session = Depends(get_db)):
    """Stores the order and returns at once; the file is downloaded and
    formatted in the background and then waits for approval. Sending the
    same order_id again is safe: the first one is kept (200, duplicate)."""
    existing = db.scalar(select(WebsiteOrder).where(WebsiteOrder.external_id == body.order_id))
    if existing:
        response.status_code = status.HTTP_200_OK
        return _accepted(existing, duplicate=True)

    file_name = None
    if body.file_url:
        file_name = body.file_name or unquote(PurePosixPath(urlsplit(body.file_url).path).name)
        orders.check_file(body.file_url, file_name)

    order = WebsiteOrder(
        external_id=body.order_id,
        **body.model_dump(exclude={"order_id", "file_url", "file_name"}),
        file_name=file_name,
        file_url=body.file_url,
        file_status=FileStatus.queued if body.file_url else FileStatus.none,
    )
    db.add(order)
    try:
        db.commit()
    except IntegrityError:  # the same order arrived twice at once
        db.rollback()
        response.status_code = status.HTTP_200_OK
        existing = db.scalar(select(WebsiteOrder).where(WebsiteOrder.external_id == body.order_id))
        return _accepted(existing, duplicate=True)
    if order.file_status is FileStatus.queued:
        background.add_task(orders.process_order_file, order.id)
    return _accepted(order, duplicate=False)
