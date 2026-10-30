"""Trillboards programmatic fill.

When a screen has no paid ads to play, it shows Trillboards' programmatic ads
instead, so idle screen time still earns money. Each of our screens is
registered once as a Trillboards partner device (server side, so the partner
API key never reaches a tablet). Trillboards answers with an embed URL; the
manifest hands that URL to the tablet, which opens it in a full screen
WebView whenever its own loop is empty.

Partner API: https://api.trillboards.com/v1/partner (Bearer TRILLBOARDS_API_KEY).
Get a key with `npx @trillboards/ads-sdk init` or POST /v1/partner/register.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import Device

log = logging.getLogger(__name__)

API = "https://api.trillboards.com/v1/partner"
EMBED_BASE = "https://screen.trillboards.com"

# Don't retry a failed registration more often than this.
RETRY_AFTER = timedelta(minutes=15)


class TrillboardsError(Exception):
    """Trillboards refused a request or couldn't be reached."""


def configured() -> bool:
    return bool(settings.trillboards_api_key) and settings.trillboards_enabled


def _request(method: str, path: str, json: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {settings.trillboards_api_key}"}
    try:
        r = httpx.request(method, API + path, json=json, headers=headers, timeout=15)
    except httpx.HTTPError as e:
        raise TrillboardsError(f"Couldn't reach Trillboards: {e}") from e
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        message = None
        if isinstance(body, dict):
            err = body.get("error")
            message = (err.get("message") if isinstance(err, dict) else err) or body.get("message")
        raise TrillboardsError(message or f"Trillboards error {r.status_code}")
    # Some endpoints wrap the result in {"data": {...}}.
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    return body if isinstance(body, dict) else {}


def partner_device_id(device: Device) -> str:
    """Our id for the screen on Trillboards' side (stable across re-pairing)."""
    return f"lfa-{device.id}"


def device_payload(device: Device) -> dict:
    location: dict = {"venue_type": settings.trillboards_venue_type}
    if device.venue_name:
        location["venue_name"] = device.venue_name
    if device.latitude is not None and device.longitude is not None:
        location["lat"] = device.latitude
        location["lng"] = device.longitude
    if device.venue_address:
        location["address"] = device.venue_address
    return {
        "device_id": partner_device_id(device),
        "device_type": "tablet",
        "name": device.name or device.venue_name or f"Screen {str(device.id)[:8]}",
        # Every ad on our network plays vertical.
        "display": {"width": 1080, "height": 1920, "orientation": "portrait"},
        "display_settings": {
            "content_fit": {
                "advertisements": "fit",
                "default_streams": "fit",
                "self_promo": "fit",
            }
        },
        "location": location,
    }


def embed_url_from(result: dict) -> str | None:
    url = result.get("embed_url") or result.get("embedUrl")
    if url:
        return str(url)
    fingerprint = result.get("fingerprint") or result.get("fp")
    if fingerprint:
        return f"{EMBED_BASE}?fp={fingerprint}"
    return None


def needs_registration(device: Device, now: datetime | None = None) -> bool:
    if not configured() or not device.programmatic_fill or device.trillboards_embed_url:
        return False
    if device.token_hash is None:  # not paired
        return False
    now = now or datetime.now(timezone.utc)
    last = device.trillboards_attempted_at
    return last is None or now - last >= RETRY_AFTER


def register(db: Session, device: Device) -> str | None:
    """Registers the screen with Trillboards and stores its embed URL.
    Never raises: a failure is kept on the device and retried later."""
    device.trillboards_attempted_at = datetime.now(timezone.utc)
    try:
        result = _request("POST", "/device", json=device_payload(device))
        url = embed_url_from(result)
        if not url:
            raise TrillboardsError("Trillboards didn't return an embed URL")
        device.trillboards_embed_url = url
        device.trillboards_screen_id = (
            str(result.get("screen_id") or result.get("screenId") or "") or None
        )
        device.trillboards_error = None
    except TrillboardsError as e:
        log.warning("Trillboards registration failed for %s: %s", device.id, e)
        device.trillboards_error = str(e)[:500]
    db.commit()
    return device.trillboards_embed_url


def register_in_background(device_id) -> None:
    """For FastAPI BackgroundTasks: uses its own database session."""
    from .db import SessionLocal

    db = SessionLocal()
    try:
        device = db.get(Device, device_id)
        if device is not None and needs_registration(device):
            register(db, device)
    finally:
        db.close()


def fallback_url(device: Device) -> str | None:
    """The URL the tablet opens when it has nothing of ours to play."""
    if not settings.trillboards_enabled or not device.programmatic_fill:
        return None
    return device.trillboards_embed_url
