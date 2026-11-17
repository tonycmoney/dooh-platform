"""Hosts: businesses with screens on their walls.

Admin endpoints (dashboard) create hosts, assign screens and send monthly
payouts. Public endpoints serve each host's private page, found by the secret
token in its link, where the host sees what its screens earned and sets up
Stripe payouts."""

import logging
import secrets
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import host_agreement, host_revenue, notify, schemas, stripe_api
from ..config import settings
from ..db import get_db
from ..models import Device, Host, HostPayout
from ..security import require_admin

log = logging.getLogger("dooh.hosts")
admin = APIRouter(prefix="/api/admin/hosts", tags=["hosts"], dependencies=[Depends(require_admin)])
public = APIRouter(prefix="/api/host", tags=["hosts"])


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _host_link(host: Host) -> str:
    return f"{settings.public_url.rstrip('/')}/host/{host.access_token}"


def _payout_status(host: Host) -> str:
    if not host.stripe_account_id:
        return "not_started"
    return "ready" if host.payouts_enabled else "pending"


def _month_out(m: host_revenue.HostMonth) -> schemas.HostMonthOut:
    return schemas.HostMonthOut(
        month=m.month, monthly_fee=m.monthly_fee, revenue=m.revenue, earnings=m.earnings,
        screens=[schemas.HostScreenMonthOut(**vars(s)) for s in m.screens],
        payout=schemas.PayoutOut.model_validate(m.payout) if m.payout else None,
    )


def _host_out(db: Session, host: Host, revenue_cache: dict) -> schemas.HostOut:
    this = host_revenue.current_month()
    last = host_revenue.recent_months(this, 2)[1]

    def month(m: date) -> schemas.HostMonthOut:
        if m not in revenue_cache:
            start, end = host_revenue.month_bounds(m)
            revenue_cache[m] = host_revenue.revenue_by_device(db, start, end)
        return _month_out(host_revenue.host_month(db, host, m, device_revenue=revenue_cache[m]))

    return schemas.HostOut(
        id=host.id, name=host.name, business_name=host.business_name, email=host.email, phone=host.phone,
        address=host.address, monthly_fee=host.monthly_fee, link=_host_link(host),
        payout_status=_payout_status(host), agreement_signed_name=host.agreement_signed_name,
        agreement_signed_at=host.agreement_signed_at,
        device_ids=[d.id for d in host.devices], this_month=month(this), last_month=month(last),
        created_at=host.created_at,
    )


def _commit_host(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Another host already uses that email.") from e


def _get_host(db: Session, host_id: uuid.UUID) -> Host:
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Host not found")
    return host


def _refresh_payout_status(db: Session, host: Host) -> None:
    """Asks Stripe whether a host finished onboarding (once it has, it stays)."""
    if host.stripe_account_id and not host.payouts_enabled and stripe_api.configured():
        try:
            if stripe_api.payouts_ready(host.stripe_account_id):
                host.payouts_enabled = True
                db.commit()
        except stripe_api.StripeError as e:
            log.warning("Couldn't check Stripe account for host %s: %s", host.id, e)


# --- Admin ----------------------------------------------------------------------


@admin.get("", response_model=list[schemas.HostOut])
def list_hosts(db: Session = Depends(get_db)):
    cache: dict = {}
    hosts = db.scalars(select(Host).order_by(Host.business_name)).all()
    return [_host_out(db, h, cache) for h in hosts]


@admin.post("", response_model=schemas.HostOut, status_code=201)
def create_host(body: schemas.HostIn, db: Session = Depends(get_db)):
    host = Host(
        name=body.name, business_name=body.business_name, email=body.email or None, phone=body.phone or None,
        address=body.address or None,
        monthly_fee=settings.host_monthly_fee if body.monthly_fee is None else body.monthly_fee, share_percent=0,
        access_token=_new_token(),
    )
    db.add(host)
    _commit_host(db)
    return _host_out(db, host, {})


@admin.patch("/{host_id}", response_model=schemas.HostOut)
def update_host(host_id: uuid.UUID, body: schemas.HostUpdate, db: Session = Depends(get_db)):
    host = _get_host(db, host_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key in ("name", "business_name", "monthly_fee") and value is None:
            continue
        setattr(host, key, (value or None) if key in ("email", "phone", "address") else value)
    _commit_host(db)
    return _host_out(db, host, {})


@admin.delete("/{host_id}", status_code=204)
def delete_host(host_id: uuid.UUID, db: Session = Depends(get_db)):
    host = _get_host(db, host_id)
    if db.scalar(select(HostPayout.id).where(HostPayout.host_id == host.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This host has been paid before, so it's kept for your records.")
    db.execute(update(Device).where(Device.host_id == host.id).values(host_id=None))
    db.delete(host)
    db.commit()


@admin.post("/{host_id}/reset-link", response_model=schemas.HostOut)
def reset_link(host_id: uuid.UUID, db: Session = Depends(get_db)):
    host = _get_host(db, host_id)
    host.access_token = _new_token()
    db.commit()
    return _host_out(db, host, {})


@admin.put("/{host_id}/screens", response_model=schemas.HostOut)
def assign_screens(host_id: uuid.UUID, body: schemas.HostScreensIn, db: Session = Depends(get_db)):
    host = _get_host(db, host_id)
    ids = set(body.device_ids)
    found = set(db.scalars(select(Device.id).where(Device.id.in_(ids))).all()) if ids else set()
    if missing := ids - found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Screen not found: {next(iter(missing))}")
    db.execute(update(Device).where(Device.host_id == host.id, Device.id.not_in(ids)).values(host_id=None))
    if ids:
        db.execute(update(Device).where(Device.id.in_(ids)).values(host_id=host.id))
    db.commit()
    db.refresh(host)
    return _host_out(db, host, {})


@admin.get("/{host_id}/months/{month}", response_model=schemas.HostMonthOut)
def host_statement(host_id: uuid.UUID, month: date, db: Session = Depends(get_db)):
    return _month_out(host_revenue.host_month(db, _get_host(db, host_id), month))


@admin.post("/{host_id}/payouts", response_model=schemas.PayoutOut, status_code=201)
def pay_host(host_id: uuid.UUID, body: schemas.PayoutIn, db: Session = Depends(get_db)):
    """Sends a finished month's earnings to the host's Stripe account. Each
    month can be paid once; Stripe's idempotency key makes a retried request
    safe."""
    host = _get_host(db, host_id)
    month = host_revenue.month_start(body.month)
    if month >= host_revenue.current_month():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only finished months can be paid.")
    if db.scalar(select(HostPayout).where(HostPayout.host_id == host.id, HostPayout.month == month)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This month has already been paid.")
    _refresh_payout_status(db, host)
    if not host.stripe_account_id or not host.payouts_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "This host hasn't finished payout setup yet. Send them their link to set it up.")
    statement = host_revenue.host_month(db, host, month)
    if statement.earnings <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to pay for this month.")
    try:
        transfer_id = stripe_api.create_transfer(
            amount=statement.earnings, currency="usd", destination=host.stripe_account_id,
            description=f"{host.business_name}: screen earnings for {month:%B %Y}",
            metadata={"host_id": str(host.id), "month": month.isoformat()},
            idempotency_key=f"host-payout-{host.id}-{month.isoformat()}",
        )
    except stripe_api.StripeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Stripe: {e}") from e
    payout = HostPayout(host_id=host.id, month=month, amount=statement.earnings, currency="USD",
                        stripe_transfer_id=transfer_id)
    db.add(payout)
    db.commit()
    log.info("Paid host %s %s cents for %s (%s)", host.id, payout.amount, month, transfer_id)
    return payout


# --- Host's private page -------------------------------------------------------------


def _host_by_token(db: Session, token: str) -> Host:
    host = db.scalar(select(Host).where(Host.access_token == token)) if len(token) >= 20 else None
    if host is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This host link isn't valid. Ask us for a new one.")
    return host


@public.get("/{token}", response_model=schemas.HostPortalOut)
def host_portal(token: str, month: date | None = Query(default=None), db: Session = Depends(get_db)):
    return build_portal(db, _host_by_token(db, token), month)


def build_portal(db: Session, host: Host, month: date | None = None) -> schemas.HostPortalOut:
    """What a host sees: earnings for `month` (default this month), the last
    6 months and the payouts sent."""
    _refresh_payout_status(db, host)
    this = host_revenue.current_month()
    selected = host_revenue.month_start(month) if month else this
    if selected > this:
        selected = this
    history = [_month_out(host_revenue.host_month(db, host, m)) for m in host_revenue.recent_months(this, 6)]
    current = next((h for h in history if h.month == selected), None) \
        or _month_out(host_revenue.host_month(db, host, selected))
    payouts = db.scalars(select(HostPayout).where(HostPayout.host_id == host.id)
                         .order_by(HostPayout.month.desc())).all()
    return schemas.HostPortalOut(
        agreement=agreement_out(host),
        business_name=host.business_name, name=host.name, monthly_fee=host.monthly_fee,
        timezone=settings.timezone, payout_status=_payout_status(host),
        payouts_available=stripe_api.configured(), month=current, history=history,
        payouts=[schemas.PayoutOut.model_validate(p) for p in payouts],
    )


def agreement_out(host: Host) -> schemas.AgreementOut:
    return schemas.AgreementOut(
        signed=host.agreement_signed_at is not None,
        signed_name=host.agreement_signed_name,
        signed_at=host.agreement_signed_at,
        title=host_agreement.TITLE,
        company_line=host_agreement.COMPANY_LINE,
        details=[schemas.AgreementDetailOut(label=k, value=v) for k, v in host_agreement.details(host)],
        sections=[schemas.AgreementSectionOut(heading=h, body=b) for h, b in host_agreement.sections(host)],
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _email_signed_copy(host: Host) -> None:
    text = (host.agreement_text or "") + host_agreement.signature_block(host)
    subject = f"Signed: {host_agreement.TITLE}, {host.business_name}"
    # The owner's copy, then the host's copy.
    notify.send_email(subject, f"{host.name} signed the host agreement.\n\n{text}")
    if host.email:
        notify.send_email(
            f"Your signed {host_agreement.TITLE} with Local Flyer Ads",
            f"Hi {host.name},\n\nThanks for hosting a Local Flyer Ads screen. Here is a copy of the agreement "
            f"you signed. Your host page, where you see your earnings and set up payouts, is here:\n"
            f"{_host_link(host)}\n\nQuestions? Call (475) 258 8963.\n\n{text}",
            to=[host.email], reply_to=settings.host_email_reply_to or None,
            sender=settings.host_email_from or None,
        )


@public.post("/{token}/agreement", response_model=schemas.AgreementOut)
def sign_agreement(token: str, body: schemas.AgreementSignIn, request: Request, db: Session = Depends(get_db)):
    """The host signs the agreement by typing their name and tapping I Agree.
    Signing twice keeps the first signature."""
    host = _host_by_token(db, token)
    if host.agreement_signed_at is not None:
        return agreement_out(host)
    if not body.agree:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Check the box to agree before signing.")
    host.agreement_text = host_agreement.as_text(host)
    host.agreement_signed_name = body.name
    host.agreement_signed_at = datetime.now(timezone.utc)
    host.agreement_signed_ip = _client_ip(request)
    host.agreement_version = host_agreement.VERSION
    db.commit()
    log.info("Host %s signed the agreement", host.id)
    try:
        _email_signed_copy(host)
    except Exception:  # the signature is saved; a failed email shouldn't undo it
        log.exception("Couldn't email the signed agreement for host %s", host.id)
    return agreement_out(host)


@public.post("/{token}/payout-setup", response_model=schemas.OnboardingLinkOut)
def payout_setup(token: str, db: Session = Depends(get_db)):
    """Starts (or resumes) Stripe's hosted payout onboarding for the host,
    once they've signed the host agreement."""
    host = _host_by_token(db, token)
    if host.agreement_signed_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Please sign the host agreement first.")
    page = _host_link(host)
    return start_payout_setup(db, host, refresh_url=f"{page}?setup=retry", return_url=f"{page}?setup=done")


def start_payout_setup(db: Session, host: Host, refresh_url: str, return_url: str) -> schemas.OnboardingLinkOut:
    if not stripe_api.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Payouts aren't open yet. We'll let you know.")
    try:
        if not host.stripe_account_id:
            host.stripe_account_id = stripe_api.create_express_account(host.email, host.business_name, str(host.id))
            db.commit()
        url = stripe_api.onboarding_link(host.stripe_account_id, refresh_url=refresh_url, return_url=return_url)
    except stripe_api.StripeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Stripe: {e}") from e
    return schemas.OnboardingLinkOut(url=url)
