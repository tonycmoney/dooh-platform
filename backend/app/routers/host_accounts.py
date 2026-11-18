"""Host accounts on the customer website.

Hosts sign in on the website (it owns logins and verifies each host's email).
The website's server then calls these endpoints with WEBSITE_API_KEY and the
signed in host's email, so a host only ever sees and changes its own data.
A host adds a tablet by typing the code the tablet shows on screen."""

import uuid
from datetime import date, datetime, timezone
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import schemas
from ..config import settings
from ..db import get_db
from ..models import Device, Host
from ..security import new_secret, sha256_hex
from .hosts import _new_token, build_portal, start_payout_setup
from .website import require_website_key

router = APIRouter(prefix="/api/website/hosts", tags=["host accounts"],
                   dependencies=[Depends(require_website_key)])

Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=255,
                                         pattern=r"^[^@\s]+@[^@\s]+$")]
Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=6, max_length=6)]


class HostRef(BaseModel):
    email: Email
    month: date | None = None


class HostRegisterIn(BaseModel):
    email: Email
    name: Text200
    business_name: Text200
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None


class AddTabletIn(BaseModel):
    email: Email
    pairing_code: Code
    name: Text200  # where it hangs, e.g. "Front counter"
    venue_address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""


class PayoutSetupIn(BaseModel):
    email: Email
    return_url: str  # the website page to come back to


class HostAccountOut(schemas.HostPortalOut):
    email: str
    phone: str | None


def find_host(db: Session, email: str) -> Host | None:
    return db.scalar(select(Host).where(func.lower(Host.email) == email.lower()).order_by(Host.created_at))


def _host(db: Session, email: str) -> Host:
    host = find_host(db, email)
    if host is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no_host")
    return host


def _account(db: Session, host: Host, month: date | None = None) -> HostAccountOut:
    portal = build_portal(db, host, month)
    return HostAccountOut(**portal.model_dump(), email=host.email or "", phone=host.phone)


@router.post("/account", response_model=HostAccountOut)
def account(body: HostRef, db: Session = Depends(get_db)):
    """The signed in host's page. 404 `no_host` means they haven't finished
    sign up (business name) yet."""
    return _account(db, _host(db, body.email), body.month)


@router.post("/register", response_model=HostAccountOut, status_code=201)
def register(body: HostRegisterIn, response: Response, db: Session = Depends(get_db)):
    """Creates the host for this email, or returns the existing one."""
    host = find_host(db, body.email)
    if host is not None:
        response.status_code = status.HTTP_200_OK
        return _account(db, host)
    host = Host(email=body.email, name=body.name, business_name=body.business_name, phone=body.phone or None,
                share_percent=settings.host_default_share_percent, access_token=_new_token())
    db.add(host)
    try:
        db.commit()
    except IntegrityError:  # signed up twice at once
        db.rollback()
        response.status_code = status.HTTP_200_OK
        host = _host(db, body.email)
    return _account(db, host)


def _network_loop(db: Session) -> uuid.UUID | None:
    """The loop most screens play, so a new tablet joins the network."""
    return db.scalar(
        select(Device.loop_id).where(Device.paired_at.is_not(None), Device.loop_id.is_not(None))
        .group_by(Device.loop_id).order_by(func.count().desc()).limit(1)
    )


@router.post("/tablets", response_model=HostAccountOut, status_code=201)
def add_tablet(body: AddTabletIn, db: Session = Depends(get_db)):
    """Pairs the tablet showing `pairing_code` and adds it to the host."""
    host = _host(db, body.email)
    device = db.scalar(select(Device).where(Device.pairing_code == body.pairing_code))
    if device is None or device.claim_secret_hash is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No tablet is showing that code. Check the code on the tablet screen and try again.")
    token = new_secret()
    device.token_hash = sha256_hex(token)
    device.pending_token = token  # collected once by the tablet, then cleared
    device.pairing_code = None
    device.paired_at = datetime.now(timezone.utc)
    device.name = body.name
    device.venue_name = host.business_name
    device.venue_address = body.venue_address or device.venue_address
    device.host_id = host.id
    if device.loop_id is None:
        device.loop_id = _network_loop(db)
    db.commit()
    db.refresh(host)
    return _account(db, host)


def _allowed_return(url: str) -> str:
    parts = urlsplit(url)
    allowed = [h.strip().lower() for h in settings.website_hosts.split(",") if h.strip()]
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not any(host == a or host.endswith("." + a) for a in allowed):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "return_url must be a page on the website")
    return url


@router.post("/payout-setup", response_model=schemas.OnboardingLinkOut)
def payout_setup(body: PayoutSetupIn, db: Session = Depends(get_db)):
    host = _host(db, body.email)
    page = _allowed_return(body.return_url).split("?")[0]
    return start_payout_setup(db, host, refresh_url=f"{page}?setup=retry", return_url=f"{page}?setup=done")
